from dataclasses import replace
from typing import Callable

from app.domain.models import Source, EditPlan, EditCandidate, Transcript
from app.adapters.base import VoiceAdapter, LipSyncAdapter
from app.continuity.engine import ContinuityEngine

# Progress is reported as (fraction, human-readable step). The fractions are
# rough weights, not measurements — lip-sync dominates once it is a real vendor.
ReportFn = Callable[[float, str], None]

# Shown on every candidate spoken in a premade voice. The continuity scores are
# still mocked (Phase 6), so without this a stock voice would sit beside an
# untroubled voice-match score and look like the speaker.
STOCK_VOICE_WARNING = "Stock voice — this is not the speaker's voice yet."


def _noop(_progress: float, _step: str) -> None:
    pass


def run_edit(
    candidate_id: str,
    plan: EditPlan,
    source: Source,
    voice: VoiceAdapter,
    lipsync: LipSyncAdapter,
    continuity: ContinuityEngine,
    report: ReportFn = _noop,
    transcript: Transcript | None = None,
) -> EditCandidate:
    """Run one dialogue edit through generation + continuity checking.

    The candidate is returned with its id already attached so the caller can
    persist it verbatim — approval must commit the exact media the user
    previewed, which re-running this function could not guarantee once the
    adapters are real (and non-deterministic) vendors.
    """
    report(0.15, "Synthesizing the new line")
    audio = voice.synthesize(source, plan, transcript)

    report(0.55, "Matching mouth movement")
    frames = lipsync.sync(source, plan, audio)

    report(0.85, "Checking continuity")
    report_card = continuity.evaluate(plan, audio, frames)
    if getattr(voice, "identity", "mock") == "stock":
        # A label, not a failure: `passed` is left alone so the edit can still
        # be approved and exported.
        report_card = replace(
            report_card, warnings=(*report_card.warnings, STOCK_VOICE_WARNING),
        )

    return EditCandidate(
        candidate_id=candidate_id, plan=plan, audio=audio, frames=frames,
        continuity=report_card,
    )
