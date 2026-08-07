from app.domain.models import Selection
from app.orchestrator.planner import extract_new_text, build_edit_plan


def test_extract_new_text_from_change_to_pattern():
    assert extract_new_text('change "20% off" to "30% off"') == "30% off"


def test_extract_new_text_falls_back_to_whole_prompt():
    assert extract_new_text("make her say hello there") == "make her say hello there"


def test_build_edit_plan_uses_selection_and_voice():
    plan = build_edit_plan(
        prompt='change "20% off" to "30% off"',
        selection=Selection(0.4, 1.3),
        voice_profile_id="speaker-1",
    )
    assert plan.new_text == "30% off"
    assert plan.selection == Selection(0.4, 1.3)
    assert plan.voice_profile_id == "speaker-1"
