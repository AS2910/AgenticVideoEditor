from app.domain.models import Selection, EditPlan
from app.continuity.engine import ContinuityEngine

GOOD_PLAN = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
BAD_PLAN = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")


def test_known_voice_passes_continuity():
    report = ContinuityEngine().evaluate(GOOD_PLAN, "audio://x", "frames://x")
    assert report.passed is True
    assert report.warnings == ()
    assert report.voice_match >= 0.8


def test_unknown_voice_fails_with_warning():
    report = ContinuityEngine().evaluate(BAD_PLAN, "audio://x", "frames://x")
    assert report.passed is False
    assert any("voice" in w.lower() for w in report.warnings)
