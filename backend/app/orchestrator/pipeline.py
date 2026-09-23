from dataclasses import replace
from typing import Callable

from app.adapters.base import VoiceAdapter, LipSyncAdapter
from app.budget import BudgetExceeded
from app.continuity.engine import Assessment
from app.domain.models import Source, EditPlan, EditCandidate, Transcript, ContinuityReport
from app.media.ffmpeg import SpanMismatch

# Progress is reported as (fraction, human-readable step). The fractions are
# rough weights, not measurements — lip-sync dominates once it is a real vendor.
ReportFn = Callable[[float, str], None]

# Shown on every candidate spoken in a premade voice, so a stock voice is never
# passed off as the speaker's.
STOCK_VOICE_WARNING = "Stock voice — this is not the speaker's voice yet."


def _noop(_progress: float, _step: str) -> None:
    pass


def _score(report: ContinuityReport) -> float:
    """How good a take is, for picking the best: its weakest measured score."""
    values = [v for v in (report.voice_match, report.prosody,
                          report.audio_integration, report.lip_sync) if v is not None]
    if not values:
        return 1.0 if report.passed else 0.0
    return min(values)


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
    regenerations = max_regenerations if getattr(voice, "identity", "mock") != "mock" else 0
    takes = 1 + regenerations
    best: Assessment | None = None
    made = 0
    notes: list[str] = []
    unfitted: SpanMismatch | None = None

    for take in range(1, takes + 1):
        span = 0.6 / takes
        base = 0.1 + span * (take - 1)
        report(base, "Synthesizing the new line" if take == 1
               else f"Regenerating the line (take {take} of {takes})")
        try:
            audio = voice.synthesize(source, plan, transcript)
        except BudgetExceeded:
            if best is None:
                raise
            notes.append("Stopped regenerating: the voice budget is used up.")
            break
        except SpanMismatch as exc:
            # Take lengths vary per call, so another take may fit. Paid all
            # the same, so it still counts as a take.
            unfitted = exc
            made += 1
            continue
        made += 1

        report(base + span / 2, "Checking continuity")
        assessed = continuity.assess(source, transcript, plan, audio)
        if best is None or _score(assessed.report) > _score(best.report):
            best = assessed
        if assessed.report.passed:
            break

    if best is None:
        # No take fitted the selection (or budget ran out before any did).
        raise unfitted or RuntimeError("no take was generated")

    report(0.75, "Matching mouth movement")
    frames = lipsync.sync(source, plan, best.audio)

    warnings = list(best.report.warnings)
    if made > 1:
        warnings.append(f"Regenerated {made - 1}× to improve continuity.")
    warnings.extend(notes)
    if getattr(voice, "identity", "mock") == "stock":
        # A label, not a failure: `passed` is left alone so the edit can still
        # be approved and exported.
        warnings.append(STOCK_VOICE_WARNING)

    return EditCandidate(
        candidate_id=candidate_id, plan=plan, audio=best.audio, frames=frames,
        continuity=replace(best.report, warnings=tuple(warnings)),
    )
