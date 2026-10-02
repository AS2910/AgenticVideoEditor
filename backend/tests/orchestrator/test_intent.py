"""Reading requests (Phase 8): the offline rules, and what the reader is told."""
from app.domain.models import Selection, Transcript, Word
from app.orchestrator.intent import RuleInterpreter, edit_context
from app.orchestrator.questions import fit_question, mix_question

WORDS = Transcript(words=(
    Word("Get", 0.0, 0.4), Word("20%", 0.4, 0.9), Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8), Word("only", 1.8, 2.3),
))


def rules(prompt):
    return RuleInterpreter().interpret(prompt, [], edit_context(WORDS, Selection(0.4, 1.3), 2.3))


def test_change_to_takes_the_new_text():
    assert rules('change "20% off" to "30% off"').new_text == "30% off"


def test_any_quoted_line_is_the_text():
    assert rules('Add the line "Thirsty Thirsty"').new_text == "Thirsty Thirsty"


def test_no_quotes_means_the_whole_message():
    assert rules("make her say hello there").new_text == "make her say hello there"


def test_rules_never_decide_the_mix():
    assert rules('Add the line "Thirsty"').mix is None


def test_context_splits_the_words_around_the_selection():
    ctx = edit_context(WORDS, Selection(0.4, 1.3), 2.3)
    assert (ctx.before, ctx.selected, ctx.after) == ("Get", "20% off", "today only")
    assert ctx.has_speech


def test_a_selection_over_no_words_has_no_speech():
    ctx = edit_context(Transcript(words=()), Selection(2.0, 5.9), 8.0)
    assert not ctx.has_speech


def test_the_mix_question_offers_all_three():
    q = mix_question("Thirsty", edit_context(Transcript(words=()), Selection(2.0, 5.9), 8.0))
    assert [o["mix"] for o in q["options"]] == ["replace", "layer", "concatenate"]
    assert q["text"] == "Thirsty" and q["mix"] is None


def test_a_layered_short_line_says_the_original_carries_on():
    q = fit_question("Thirsty", "layer", 0.74, 3.87, 2.0, 8.0)
    assert "original sound carries on" in q["options"][0]["label"]


def test_running_past_the_end_is_offered_only_with_room():
    assert [o["fit"] for o in fit_question("x", "replace", 2.0, 0.9, 1.0, 8.0)["options"]] == ["stretch", "start"]
    assert [o["fit"] for o in fit_question("x", "replace", 2.0, 0.9, 7.0, 8.0)["options"]] == ["stretch"]


def test_a_stretch_inside_the_natural_range_carries_no_warning():
    q = fit_question("x", "replace", 1.0, 0.9, 0.0, 8.0)
    assert q["options"][0]["warning"] is None
