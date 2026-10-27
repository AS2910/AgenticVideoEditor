"""Run 5, item 10: the quality harness's verdicts. SyncNet itself is checked
live in tests/continuity/test_lipsync_measure_live.py (opt-in)."""
import pytest

from app.lipsync import quality
from app.lipsync.quality import Confidence
from app.media import ffmpeg


def test_a_result_as_good_as_the_original_passes():
    assert quality.compare(Confidence(0.8, "motion", {}), Confidence(0.7, "motion", {}))["verdict"] == "pass"


def test_a_result_well_under_the_original_is_below():
    out = quality.compare(Confidence(0.9, "motion", {}), Confidence(0.2, "motion", {}))
    assert out == {"verdict": "below", "say": "Less well synced than the original."}


def test_no_face_in_the_result_and_no_baseline_are_said_plainly():
    assert quality.compare(Confidence(0.8, "motion", {}), Confidence(None, "none", {}))["verdict"] == "no_face"
    weak = Confidence(0.3, "syncnet", {"lse_c": 2.0})
    assert quality.compare(weak, Confidence(0.9, "syncnet", {"lse_c": 8.0}))["verdict"] == "no_baseline"


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
def test_a_clip_with_no_face_has_no_score(sample_video):
    got = quality.confidence(sample_video)
    assert got.score is None and got.method == "none"
