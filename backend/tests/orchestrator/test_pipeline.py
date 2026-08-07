from app.domain.models import Source, Selection, EditPlan
from app.adapters.mock import MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.pipeline import run_edit

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=30.0)


def test_run_edit_produces_candidate_with_refs_and_report():
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run_edit(
        plan, SOURCE, MockVoiceAdapter(), MockLipSyncAdapter(), ContinuityEngine(),
    )
    assert candidate.plan == plan
    assert candidate.audio_ref.startswith("audio://")
    assert candidate.frames_ref.startswith("frames://")
    assert candidate.continuity.passed is True


def test_run_edit_surfaces_failed_continuity():
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")
    candidate = run_edit(
        plan, SOURCE, MockVoiceAdapter(), MockLipSyncAdapter(), ContinuityEngine(),
    )
    assert candidate.continuity.passed is False
