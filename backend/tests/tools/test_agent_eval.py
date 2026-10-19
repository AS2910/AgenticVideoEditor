"""The agent eval's shape (2026-10-20): goals across genres, a grade that reads as pass/fail, measured timing and chat."""
from app.tools.agent_eval import CLIPS, GOALS, Grade, RUBRIC, measured

POINTS = ("fits_scene", "delivery_matches", "placement_sensible", "nothing_committed_without_gate", "honest",
          "grounded", "genre_fit", "style_adherence", "leads_with_result")


def test_the_goals_cover_every_genre_and_the_rubric_names_every_point():
    assert {CLIPS[c][0] for c, _ in GOALS} == {"sports", "travel", "ad", "talking head", "food", "event"}
    for point in POINTS:
        assert point in RUBRIC and point in Grade.model_fields
    assert "spend_within_cap" not in Grade.model_fields        # the cap is checked from the ledger, not by the grader


def test_a_grade_parses_with_pass_as_the_model_writes_it():
    p = {"ok": True, "why": "fine"}
    g = Grade.model_validate({**{k: p for k in POINTS}, "honest": {"ok": False, "why": "claimed to have heard it"},
                              "pass": False, "note": "Chose well; said it heard the take."})
    assert g.passed is False and g.honest.ok is False
    assert g.model_dump(by_alias=True)["pass"] is False


def test_timing_and_chat_are_measured_not_judged():
    m = measured({"timing": [{"miss": 0.1}, {"miss": -0.5}, {"miss": None}], "reply": "Take c3 is ready in its slot.", "goal": ""})
    assert m["timing"] == {"on_beat": 1, "of": 2}
    assert set(m["chat"]["issues"]) == {"uses slot", "uses a take id"}
