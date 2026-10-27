from dataclasses import replace
from typing import Callable

from app.adapters.base import LipSyncAdapter, VendorError, VoiceAdapter
from app.budget import BudgetExceeded
from app.errors import NonRetryableError
from app.continuity.engine import Assessment
from app.domain.models import (
    Source, EditPlan, EditCandidate, Transcript, ContinuityReport, Selection,
)
from app.continuity import prosody
from app.media import fit
from app.media.ffmpeg import SpanMismatch

# Progress is reported as (fraction, human-readable step). The fractions are
# rough weights, not measurements — lip-sync dominates once it is a real vendor.
ReportFn = Callable[[float, str], None]

# Shown on every candidate spoken in a premade voice, so a stock voice is never
# passed off as the speaker's. (Phase 15a: when the line says why it is stock —
# too little speech to clone — that sentence stands in its place.)
STOCK_VOICE_WARNING = "Stock voice: this is not the speaker's voice yet."


def identity_of(voice: VoiceAdapter, plan: EditPlan) -> str:
    """Whose voice this take is: "mock", "stock" or "clone". An adapter that
    can clone says so per take (the speaker has a clone or does not); one that
    cannot has one identity throughout."""
    per_take = getattr(voice, "identity_for", None)
    return per_take(plan) if per_take else getattr(voice, "identity", "mock")


def _noop(_progress: float, _step: str) -> None:
    pass


def _score(report: ContinuityReport) -> float:
    """How good a take is, for picking the best: its weakest measured score.
    Run 5 item 7: the prosody distance counts as a score (0.8 at one point of
    distance, the bar the others pass at), and a take refused for its delivery
    ranks below every take that was not."""
    values = [v for v in (report.voice_match, report.prosody,
                          report.audio_integration, report.lip_sync,
                          prosody.score(getattr(report, "prosody_distance", None))) if v is not None]
    if not values:
        return 1.0 if report.passed else 0.0
    refused = any(w.startswith(_REFUSALS) for w in report.warnings)
    return min(values) - (1.0 if refused else 0.0)


# The warnings `prosody.judge` writes for a take outside the speaker's range.
_REFUSALS = ("Said faster than the lines", "Said slower than the lines", "Flatter than the lines",
             "More sing-song than the lines", "Pitched higher than the lines", "Pitched lower than the lines")


def _settings_note(settings: dict | None) -> str | None:
    """The fit note that says a take was steered toward the speaker, and how."""
    if not settings:
        return None
    return "delivery matched to the speaker: " + ", ".join(f"{k} {v:g}" for k, v in sorted(settings.items()))


def _speak_like(voice, source: Source, plan: EditPlan, transcript: Transcript | None, notes: list[str]):
    """Run 5 item 7: a line whose words do not change (a new voice for the same
    words) is the original line itself, passed through the Voice Changer into
    the new voice, so its pace, energy and emotion are the speaker's own. None
    when that does not apply or the vendor could not do it; the caller then
    synthesises as before."""
    if plan.mix != "replace" or plan.delivery or plan.voice_settings or not hasattr(voice, "speak_like") \
            or not prosody.same_words(transcript, plan.selection, plan.new_text):
        return None
    try:
        audio = voice.speak_like(source, plan, transcript)
    except BudgetExceeded:
        raise
    except (VendorError, NonRetryableError):
        notes.append("Could not carry the original delivery over, so the line was voiced from its words.")
        return None
    return audio


def _revoiced(voice, continuity, source, transcript, plan, assessed: Assessment,
              identity: str, route: str, notes: list[str], dry=None) -> Assessment:
    """The Voice Changer rung (Phase 15b): a take in the speaker's clone is
    passed through it again when the measured match is weak (route "auto"), or
    always (route "changer"). The converted take is kept only if it does not
    score worse; a vendor failure keeps the take as it was, and says so."""
    if route == "tts" or identity != "clone" or not hasattr(voice, "revoice"):
        return assessed
    floor = getattr(getattr(continuity, "thresholds", None), "voice_match", 0.75)
    match = assessed.report.voice_match
    if route == "auto" and (match is None or match >= floor):
        return assessed
    try:
        # Run 5 item 7: the dry take, before level, room and room tone (they
        # are put on again when the converted take is assessed).
        converted = voice.revoice(source, plan, dry or assessed.audio)
    except BudgetExceeded:
        notes.append("The voice budget ran out before the Voice Changer could improve the match.")
        return assessed
    except (VendorError, NonRetryableError):
        notes.append("The Voice Changer was unavailable, so the first take stands.")
        return assessed
    if converted is None:
        return assessed
    again = continuity.assess(source, transcript, plan, converted)
    if route == "changer" or _score(again.report) >= _score(assessed.report):
        notes.append("Passed through the Voice Changer for a closer match to the speaker.")
        return again
    return assessed


def run_edit(
    candidate_id: str,
    plan: EditPlan,
    source: Source,
    voice: VoiceAdapter,
    lipsync: LipSyncAdapter,
    continuity,
    report: ReportFn = _noop,
    transcript: Transcript | None = None,
    max_regenerations: int = 0,
    voice_notes: tuple[str, ...] = (),
    route: str = "tts",
) -> EditCandidate:
    """Run one dialogue edit through generation + continuity checking.

    A take that fails continuity is regenerated (spec §6: auto-retry before the
    user sees it), up to `max_regenerations` more times, keeping the best take.
    Only a real voice is regenerated — the mock is deterministic, so a second
    take would be identical. Each take is a paid call charged to the budget; if
    the budget runs out mid-loop the best take so far is kept.

    Lip-sync runs once, on the winning audio: it is the expensive step once it
    is a real vendor, and only the audio decides which take wins.

    The candidate is returned with its id already attached so the caller can
    persist it verbatim — approval must commit the exact media the user
    previewed, which re-running this function could not guarantee once the
    adapters are real (and non-deterministic) vendors.
    """
    identity = identity_of(voice, plan)
    regenerations = max_regenerations if identity != "mock" else 0
    takes = 1 + regenerations
    best: Assessment | None = None
    made = 0
    notes: list[str] = []
    fit_notes: tuple[str, ...] = ()
    words: tuple = ()
    unfitted: SpanMismatch | None = None
    # Run 5 item 7: the first take follows the original line's delivery; a take
    # refused for its delivery is retaken with the settings that move it back.
    # Only `voice.synthesize` sees these; the plan kept and assessed is as asked.
    reference = getattr(continuity, "reference", None)
    steered = reference(source, transcript, plan) if reference and identity != "mock" else None

    for take in range(1, takes + 1):
        span = 0.6 / takes
        base = 0.1 + span * (take - 1)
        if take == 1:
            report(base, "Synthesizing the new line")
        else:
            why = next((w for w in best.report.warnings), None) if best else None
            report(base, (f"Take {take - 1}: {why[0].lower() + why[1:].rstrip('.')}. "
                          f"Trying again (take {take} of {takes})") if why
                   else f"Regenerating the line (take {take} of {takes})")
        try:
            take_plan = replace(plan, voice_settings=steered) if steered else plan
            audio = _speak_like(voice, source, plan, transcript, notes) if take == 1 and identity != "mock" else None
            spoken_like = audio is not None
            if audio is None:
                audio = voice.synthesize(source, take_plan, transcript)
        except BudgetExceeded:
            if best is None:
                raise
            notes.append("Stopped regenerating: the voice budget is used up.")
            break
        except SpanMismatch as exc:
            if best is None:
                # The first take does not fit: ask the user how to place it
                # rather than paying for more takes that may not fit either.
                raise
            # A retake that happens not to fit is skipped; one already fits.
            unfitted = exc
            made += 1
            continue
        made += 1

        report(base + span / 2, "Checking continuity")
        assessed = continuity.assess(source, transcript, plan, audio)
        if not spoken_like:
            assessed = _revoiced(voice, continuity, source, transcript, plan, assessed, identity, route, notes, dry=audio)
        if best is None or _score(assessed.report) > _score(best.report):
            best = assessed
            if spoken_like:
                fit_notes = ("spoken from the original line's delivery",)
                words = tuple(getattr(voice, "last_words", ()))
            else:
                note = _settings_note(steered)
                fit_notes = tuple(getattr(voice, "last_notes", ())) + ((note,) if note else ())
                words = tuple(getattr(voice, "last_words", ()))
        if assessed.report.passed:
            break
        if assessed.delivery is not None and not spoken_like and plan.mix == "replace" \
                and not (plan.delivery or plan.voice_settings):
            steered = prosody.steer(steered, assessed.delivery) or steered

    if best is None:
        # No take fitted the selection (or budget ran out before any did).
        raise unfitted or RuntimeError("no take was generated")

    # Phase 16: the fit may have let the picture flex so the take fits at
    # natural speech; the plan carries the factor for the renderer.
    flex = fit.flex_of(fit_notes)
    if abs(flex - 1.0) > 1e-6:
        plan = replace(plan, flex=flex)
    if best.roomed:
        plan = replace(plan, roomed=True)
    if plan.mix != "concatenate" and plan.flex is None:
        # A line placed at natural speed may run past the selection; the edit
        # then covers the whole line, or its end would be cut off.
        span = plan.selection.end - plan.selection.start
        if best.audio.duration > span + 0.01:
            plan = replace(plan, selection=Selection(
                plan.selection.start, plan.selection.start + best.audio.duration,
            ))

    report(0.75, "Matching mouth movement")
    frames = lipsync.sync(source, plan, best.audio)

    warnings = list(best.report.warnings)
    if made > 1:
        warnings.append(f"Regenerated {made - 1}× to improve continuity.")
    warnings.extend(notes)
    warnings.extend(voice_notes)
    if identity == "stock" and not voice_notes:
        # A label, not a failure: `passed` is left alone so the edit can still
        # be approved and exported.
        warnings.append(STOCK_VOICE_WARNING)

    return EditCandidate(
        candidate_id=candidate_id, plan=plan, audio=best.audio, frames=frames,
        continuity=replace(best.report, warnings=tuple(warnings)), fit_notes=fit_notes,
        words=words,
    )
