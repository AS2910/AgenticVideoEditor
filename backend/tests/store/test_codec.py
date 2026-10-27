"""Run 5 item 7: what a take measured survives the store."""
from app.domain.models import ContinuityReport, EditPlan, Selection
from app.store import codec


def test_naturalness_and_prosody_distance_survive_a_round_trip():
    report = ContinuityReport(0.8, 0.9, 0.95, None, True, ("w",), measured=("voice_match", "prosody_distance"),
                              naturalness=4.1, prosody_distance=0.42)
    assert codec.report(codec.dump(report)) == report


def test_a_report_stored_before_them_reads_as_unmeasured():
    old = {"voice_match": 0.8, "prosody": 0.9, "audio_integration": 0.95, "lip_sync": None,
           "passed": True, "warnings": [], "measured": ["prosody"]}
    report = codec.report(old)
    assert report.naturalness is None and report.prosody_distance is None


def test_a_roomed_plan_survives_and_an_old_plan_is_not_roomed():
    plan = EditPlan(Selection(0.4, 1.3), "x", "v", roomed=True)
    assert codec.plan(codec.dump(plan)).roomed is True
    old = codec.dump(EditPlan(Selection(0.4, 1.3), "x", "v"))
    old.pop("roomed")
    assert codec.plan(old).roomed is None
