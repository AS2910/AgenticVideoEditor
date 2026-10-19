"""A line's key word against its beat (2026-10-20)."""
from types import SimpleNamespace as W

from app.agent.landing import landing_note, lands_at
from app.agent.tools import BY_NAME

WORDS = (W(text="Blue", start=0.0, end=0.3), W(text="goes", start=0.3, end=0.5), W(text="DOWN!", start=0.55, end=1.0))


def test_the_key_word_lands_where_the_take_says():
    assert lands_at(WORDS, 12.5, "down") == 13.05
    assert lands_at(WORDS, 12.5, "") is None and lands_at(WORDS, 12.5, "knockout") is None


def test_within_300_ms_is_on_the_beat_and_a_miss_says_how_to_fix_it():
    note, miss = landing_note(WORDS, 12.5, "DOWN", 13.0)
    assert miss == 0.05 and "on the beat" in note
    note, miss = landing_note(WORDS, 13.0, "down", 13.0)
    assert miss == 0.55 and "late" in note and "start the line at 12.45 s" in note


def test_synthesize_take_reports_the_landing(world):
    out = BY_NAME["synthesize_take"].run(world.wb, world.turn(), {"text": "Welcome to Goa", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 2.0, "end": 4.0,
                                                                 "direction": None, "mix": "layer", "line": None, "item_id": None,
                                                                 "beat_at": 2.6, "key_word": "Goa"})
    assert "“Goa” lands at 2.60 s" in out.text and "on the beat" in out.text
