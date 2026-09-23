from typing import Callable

from app.domain.models import Source, EditPlan, EditCandidate
from app.adapters.base import VoiceAdapter, LipSyncAdapter
from app.continuity.engine import ContinuityEngine

# Progress is reported as (fraction, human-readable step). The fractions are
# rough weights, not measurements — lip-sync dominates once it is a real vendor.
ReportFn = Callable[[float, str], None]


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
) -> EditCandidate:
    """Run one dialogue edit through generation + continuity checking.

    The candidate is returned with its id already attached so the caller can
    persist it verbatim — approval must commit the exact media the user
    previewed, which re-running this function could not guarantee once the
    adapters are real (and non-deterministic) vendors.
    """
    report(0.15, "Synthesizing the new line")
    audio = voice.synthesize(source, plan)

    report(0.55, "Matching mouth movement")
    frames = lipsync.sync(source, plan, audio)

    report(0.85, "Checking continuity")
    report_card = continuity.evaluate(plan, audio, frames)

    return EditCandidate(
        candidate_id=candidate_id, plan=plan, audio=audio, frames=frames,
        continuity=report_card,
    )
