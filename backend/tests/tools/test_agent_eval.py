"""The agent eval's shape: ten goals over the three clips, a grade that reads as pass/fail."""
from app.tools.agent_eval import GOALS, Grade, RUBRIC


def test_ten_goals_cover_the_three_clips_and_the_rubric_names_every_point():
    assert len(GOALS) == 10 and {c for c, _ in GOALS} == {"goa", "bhaji", "ad"}
    for point in ("fits_scene", "delivery_matches", "placement_sensible", "spend_within_cap", "nothing_committed_without_gate", "honest"):
        assert point in RUBRIC and point in Grade.model_fields


def test_a_grade_parses_with_pass_as_the_model_writes_it():
    p = {"ok": True, "why": "fine"}
    g = Grade.model_validate({"fits_scene": p, "delivery_matches": p, "placement_sensible": p, "spend_within_cap": p,
                              "nothing_committed_without_gate": p, "honest": {"ok": False, "why": "claimed to have heard it"},
                              "pass": False, "note": "Chose well; said it heard the take."})
    assert g.passed is False and g.honest.ok is False
    assert g.model_dump(by_alias=True)["pass"] is False
