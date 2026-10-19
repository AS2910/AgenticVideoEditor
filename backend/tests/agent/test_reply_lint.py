"""The reply lint (2026-10-20), on real words and on the recorded turns."""
import json
from pathlib import Path

from app.agent.reply_lint import lint, sentences

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


def test_the_recorded_turns_pass():
    for turn in json.loads(SCRIPT.read_text())["turns"]:
        assert lint(turn.get("reply") or "") == [], turn.get("reply")
