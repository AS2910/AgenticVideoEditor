"""Run 5 item 6: the router for small edits, and the story checks after them."""
from types import SimpleNamespace

from app.agent import fastpath, story_checks
from app.agent.story_checks import StoryLine


def test_changed_words_counts_the_longer_side_of_each_changed_run():
    assert fastpath.changed_words("Get 20% off today only.", "Get 30% off today only.") == 1
    assert fastpath.changed_words("Get 20% off today only.", "Get 30% off this weekend only!") == 3
    assert fastpath.changed_words("We open at nine on weekdays.", "We open at ten on most weekdays now.") == 3
    assert fastpath.changed_words("Same words.", "same words") == 0          # case and punctuation are not words


def test_a_four_word_change_in_one_line_in_its_own_voice_goes_fast():
    r = fastpath.route("Fresh bread every single morning.", "Warm rolls every Sunday afternoon.",
                       on_line=True, new_line=False, voice_changed=False)
    assert r.fast and r.changed == 4


def test_more_than_eight_words_a_new_line_or_a_new_voice_go_the_full_way():
    long = fastpath.route("Get 20% off today.", "Get thirty percent off every single thing in the shop until Sunday.",
                          on_line=True, new_line=False, voice_changed=False)
    assert not long.fast and "words changed" in long.reason
    assert not fastpath.route("", "A new line.", on_line=False, new_line=True, voice_changed=False).fast
    assert fastpath.route("a b", "a c", on_line=True, new_line=False, voice_changed=True).reason == "a different voice"
    assert not fastpath.route("a b", "a b", on_line=True, new_line=False, voice_changed=False).fast
    assert fastpath.route("a b", "a c", on_line=True, new_line=False, voice_changed=False, over_limit=True).reason == "over your spending limit"
    assert fastpath.route("a b", "a c", on_line=True, new_line=False, voice_changed=False, question_open=True).fast is False


def test_exactly_eight_words_is_still_fast():
    before = "one two three four five six seven eight nine"
    after = "uno dos tres cuatro cinco seis siete ocho nine"
    assert fastpath.route(before, after, on_line=True, new_line=False, voice_changed=False).fast


LINES = [StoryLine(0.0, "Get 20% off today only."), StoryLine(3.0, "Our bakery opens at seven every day."),
         StoryLine(6.0, "The shop is open on Sundays."), StoryLine(9.0, "Fresh bread every single morning.")]


def test_a_percentage_another_line_still_says_differently_is_pointed_out():
    found = story_checks.check(LINES + [StoryLine(12.0, "Remember, 20% off everything.")], 0.0, "Get 30% off today only.")
    assert found == ["The line at 0:12 still says 20%, and this one now says 30%."]


def test_a_phrase_another_line_already_says_is_pointed_out():
    found = story_checks.check(LINES, 3.0, "Fresh bread every single day.")
    assert found == ["“fresh bread every single” is also said at 0:09."]


def test_a_negation_flip_reads_as_a_contradiction():
    found = story_checks.check(LINES, 9.0, "The shop is not open on Sundays.")
    assert found == ["The line at 0:06 says the opposite about “the shop is open on sundays”."]


def test_filler_repeats_and_the_changed_line_itself_are_not_flagged():
    assert story_checks.check(LINES, 3.0, "It is in the oven.") == []
    assert story_checks.check(LINES, 0.0, "Get 25% off today only.") == []
    assert story_checks.suggestion([]) is None
    assert story_checks.suggestion(["x."]).endswith("If you meant it, leave it.")


def test_lines_now_reads_the_proposal_and_the_kept_edit_over_the_words_as_shot():
    lines = [SimpleNamespace(start=0.0, end=2.0, text="as shot one"), SimpleNamespace(start=3.0, end=5.0, text="as shot two")]
    sel = lambda a, b: SimpleNamespace(start=a, end=b)   # noqa: E731
    edit = SimpleNamespace(plan=SimpleNamespace(mix="replace", selection=sel(0.0, 2.0), new_text="kept one"))
    item = SimpleNamespace(kind="planned", mix="replace", status="ready", selection=sel(3.0, 5.0), new_text="proposed two")
    assert [ln.text for ln in fastpath.lines_now(lines, [edit], [item])] == ["kept one", "proposed two"]


def test_the_line_voice_is_the_take_s_else_the_speaker_s_and_the_clone_counts_as_their_own():
    speaker = SimpleNamespace(voice_id=None, clone_voice_id="clone-a")
    assert fastpath.line_voice(None, speaker) == ("", {"clone-a"})
    assert fastpath.line_voice("clone-a", speaker) == ("clone-a", {"clone-a"})
    assert fastpath.line_voice(None, None) == ("", set())
