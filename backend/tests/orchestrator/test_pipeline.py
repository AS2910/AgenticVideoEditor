from pathlib import Path

import pytest

from app.domain.models import Selection, EditPlan
from tests.factories import make_source
from app.media import ffmpeg
from app.adapters.mock import MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.pipeline import run_edit

SOURCE = make_source()

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


def run(store, plan, candidate_id="c1"):
    return run_edit(
        candidate_id, plan, SOURCE,
        MockVoiceAdapter(store), MockLipSyncAdapter(store), ContinuityEngine(),
    )


def test_run_edit_produces_candidate_with_real_artifacts_and_report(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run(store, plan)

    assert candidate.candidate_id == "c1"
    assert candidate.plan == plan
    assert candidate.audio.kind == "audio" and Path(candidate.audio.path).is_file()
    assert candidate.frames.kind == "video" and Path(candidate.frames.path).is_file()
    assert candidate.continuity.passed is True


def test_run_edit_surfaces_failed_continuity(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")
    assert run(store, plan).continuity.passed is False


def test_audio_and_frames_cover_the_same_span(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run(store, plan)
    assert candidate.audio.duration == pytest.approx(candidate.frames.duration, abs=0.05)
