"""No em dashes in what Voltage writes (2026-10-19): the rule in the prompts,
the safety net on its prose, and the exceptions (spoken words, the user's own
text and style)."""
from types import SimpleNamespace as NS

import pytest

from app.adapters.claude_planner import LOOK_SYSTEM, READ_SYSTEM
from app.agent.context import SYSTEM
from app.agent.prose import plain, wants_dashes
from app.agent.tools import BY_NAME

RULE = "Never use em dashes in anything you write."


def test_the_prompts_carry_the_rule_and_no_em_dash_of_their_own():
    for prompt in (SYSTEM, READ_SYSTEM, LOOK_SYSTEM):
        assert RULE in prompt
        assert "—" not in prompt and "&mdash;" not in prompt   # the model copies the style of its examples
    assert "if the user uses em dashes or asks for them, you may match them" in SYSTEM


def test_the_safety_net_turns_voltages_dashes_into_commas():
    assert plain("Line 2 is ready — it fits the gap.") == "Line 2 is ready, it fits the gap."
    assert plain("Done —.") == "Done."
    assert plain("Two takes—one kept.") == "Two takes, one kept."
    assert plain("Fine &mdash; next.") == "Fine, next."


def test_quotes_and_spoken_words_are_left_exactly_as_they_are():
    said = "I voiced “Wait — what?” in Riya’s voice — calm."
    assert plain(said) == "I voiced “Wait — what?” in Riya’s voice, calm."
    assert plain('You wrote "Sale — today only" as the brief.') == 'You wrote "Sale — today only" as the brief.'


def test_a_user_who_writes_or_asks_for_em_dashes_gets_them_matched():
    assert wants_dashes("Make it punchy — short lines")
    assert wants_dashes("use em dashes in the reply please") and wants_dashes("an em-dash here")
    assert not wants_dashes("make it 30% off")
    reply = "Here it is — short and punchy."
    assert plain(reply, "Make it punchy — short lines") == reply
    assert plain(reply, "make it punchy") == "Here it is, short and punchy."


def test_narration_renders_without_em_dashes(world):
    world.lines[:] = [NS(index=1, start=0.5, end=2.0, speaker=None, text="Welcome to Goa.", syllables=5, budget=7)]
    out = BY_NAME["synthesize_take"].run(world.wb, world.turn(), {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "line": 1,
                                                                 "direction": "warm and unhurried, a half-smile", "mix": None, "item_id": None,
                                                                 "start": None, "end": None})
    assert "—" not in out.step and " · warm and unhurried, a half-smile" in out.step
    assert "—" not in out.text
    # The words to be spoken are never rewritten: a take keeps the user's dash in its own text.
    out = BY_NAME["synthesize_take"].run(world.wb, world.turn(), {"text": "Wait — what?", "voice_id": "kL06KYMvPY56NluIQ72m", "line": 1,
                                                                 "direction": None, "mix": None, "item_id": None, "start": None, "end": None})
    assert world.made[-1]["text"] == "Wait — what?"
