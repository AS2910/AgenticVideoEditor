"""The reply lint (2026-10-20), on real words and on the recorded turns."""
import json
from pathlib import Path

from app.agent.reply_lint import MAX_SENTENCES, lint, sentences, split
from app.agent.context import SYSTEM

SCRIPT = Path(__file__).resolve().parents[2] / "app" / "tutorial" / "fixture" / "script.json"


def test_internal_words_are_caught():
    bad = ("I've voiced four of the five commentary lines. The middle line (7.1 to 10.3 s) was too long for its slot, "
           "and redoing it shorter would go over this turn's $0.50 cap. Take c3 is on item i1 at -12 dB.")
    assert set(lint(bad)) >= {"uses slot", "uses turn cap", "uses a take id", "uses an item id", "uses dB"}


def test_the_good_example_passes():
    good = "Four lines of ringside commentary are ready, building to the knockdown at 0:13. Keep the middle tight, or let it breathe?\n0:00 to 0:16 · four lines · $0.38"
    assert lint(good) == []
    assert len(sentences(good)) == 2


def test_dB_is_fine_when_the_user_asked_and_length_when_they_asked_for_more():
    assert lint("The crowd sits 15 dB under the narration.", "how loud is the crowd in dB?") == []
    long = "One. Two. Three. Four."
    assert lint(long) == ["4 sentences"] and lint(long, "explain why") == []
    # Run 5 item 5: two sentences at most; a third is flagged.
    assert MAX_SENTENCES == 2 and lint("One. Two. Three.") == ["3 sentences"] and lint("One. Two.") == []


def test_the_recorded_turns_pass():
    for turn in json.loads(SCRIPT.read_text())["turns"]:
        assert lint(turn.get("reply") or "") == [], turn.get("reply")


# Run 5 item 5: at most two sentences plus the card; the rest behind "Why?".

def test_the_prompt_asks_for_two_sentences_and_names_why():
    assert "Two sentences at most" in SYSTEM and "One or two sentences, never more" in SYSTEM
    assert "Why?" in SYSTEM
    assert "Three sentences by default" not in SYSTEM and "One to three sentences" not in SYSTEM


def test_split_keeps_two_sentences_and_moves_the_rest_and_the_facts_line_behind_why():
    reply = ("Four lines of commentary are ready, building to the knockdown at 0:13. Keep the middle tight, or let it breathe? "
             "The middle line ran long, so I sped it up a little. Daniel does the play-by-play.\n0:00 to 0:16 · four lines · $0.38")
    said, why = split(reply)
    assert len(sentences(said)) <= MAX_SENTENCES
    assert said == "Four lines of commentary are ready, building to the knockdown at 0:13. Keep the middle tight, or let it breathe?"
    assert why == "The middle line ran long, so I sped it up a little. Daniel does the play-by-play.\n0:00 to 0:16 · four lines · $0.38"
    # Nothing is lost: every word is in one half or the other.
    assert sorted((said + " " + why).split()) == sorted(reply.split())


def test_split_leaves_a_short_reply_whole_and_a_long_one_the_user_asked_for():
    assert split("Line 2 is ready to hear. Add it?") == ("Line 2 is ready to hear. Add it?", "")
    long = "One. Two. Three. Four."
    assert split(long, "explain why you chose Sarah") == (long, "")
    assert split(long, "how do I export?") == (long, "")
    assert split(long) == ("One. Two.", "Three. Four.")


def test_split_never_hides_a_correction():
    reply = "Line 2 is in the video. Hear it in the player. It sounds warm.\n\nCorrection: line 2 is not in the video yet; it is proposed and waiting for your Add it."
    said, why = split(reply)
    assert "Correction: line 2 is not in the video yet" in said
    assert why == "It sounds warm."


def test_every_recorded_reply_fits_in_two_sentences():
    for turn in json.loads(SCRIPT.read_text())["turns"]:
        said, why = split(turn.get("reply") or "")
        assert len(sentences(said)) <= MAX_SENTENCES and why == "", turn.get("reply")
