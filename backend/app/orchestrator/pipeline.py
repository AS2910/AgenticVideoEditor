from app.domain.models import Source, EditPlan, EditCandidate
from app.adapters.base import VoiceAdapter, LipSyncAdapter
from app.continuity.engine import ContinuityEngine


def run_edit(
    plan: EditPlan,
    source: Source,
    voice: VoiceAdapter,
    lipsync: LipSyncAdapter,
    continuity: ContinuityEngine,
) -> EditCandidate:
    """Run one dialogue edit through generation + continuity checking."""
    audio_ref = voice.synthesize(plan.new_text, plan.voice_profile_id)
    frames_ref = lipsync.sync(source, plan, audio_ref)
    report = continuity.evaluate(plan, audio_ref, frames_ref)
    return EditCandidate(
        plan=plan, audio_ref=audio_ref, frames_ref=frames_ref, continuity=report,
    )
