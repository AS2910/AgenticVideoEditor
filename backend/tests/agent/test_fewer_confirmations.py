"""Run 5 item 2: fewer confirmations. Under Check with me, paid steps up to the
user's limit ("Ask me before spending more than $X", per turn) run without
asking; past it, one card asks, its yes named for what it does with the price.
Questions about meaning are still asked. A pick on Voltage's question is the
approval for what its card showed."""
from dataclasses import replace

import pytest

from app.agent.guards import TurnBudget, WaitingForUser
from app.agent.tools import BY_NAME, paid_this_turn

ARGS = {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
        "direction": None, "mix": None, "line": None, "item_id": None}


def ask_turn(world, auto_usd=0.25, **kw):
    return replace(world.turn(autonomy="ask", **kw), auto_usd=auto_usd)


# ── the threshold, as a rule ────────────────────────────────────────────────

@pytest.mark.parametrize("paid,step,auto,goes", [
    (0.00, 0.04, 0.25, True),     # a $0.04 voice-over: under the limit, no question
    (0.20, 0.05, 0.25, True),     # exactly at the limit still goes
    (0.20, 0.06, 0.25, False),    # past it: asks
    (0.00, 0.30, 0.25, False),    # one step bigger than the limit: asks
    (0.00, 0.01, 0.00, False),    # a limit of nothing asks before every paid step, as before
])
def test_check_with_me_goes_ahead_while_the_turns_paid_steps_stay_within_the_limit(world, paid, step, auto, goes):
    assert ask_turn(world, auto_usd=auto).may_spend(paid, step) is goes


def test_just_do_it_and_a_yes_never_ask_about_spend(world):
    assert world.turn(autonomy="draft").may_spend(5.0, 5.0)
    assert ask_turn(world, auto_usd=0.0, approved=True).may_spend(5.0, 5.0)


def test_voltages_own_thinking_does_not_count_against_the_limit(world):
    t = ask_turn(world)
    world.ledger.record("p1", "anthropic", "agent", 1000, "tokens", 0.40)
    world.ledger.record("p1", "elevenlabs", "take", 20, "characters", 0.04)
    assert paid_this_turn(world.wb, t) == pytest.approx(0.04)


# ── the voice tool ──────────────────────────────────────────────────────────

def test_a_voice_over_under_the_limit_is_voiced_without_a_question(world):
    t = ask_turn(world)
    out = BY_NAME["synthesize_take"].run(world.wb, t, ARGS)
    assert len(world.made) == 1 and "Take c1" in out.text


def test_past_the_limit_one_card_asks_and_its_yes_names_the_step_and_its_price(world):
    t = ask_turn(world, auto_usd=0.01)
    world.ledger.record("p1", "elevenlabs", "take", 20, "characters", 0.01)
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["synthesize_take"].run(world.wb, t, ARGS)
    assert w.value.gate and w.value.options == ("Voice it · $0.00", "Not yet") and w.value.guess == "Voice it · $0.00"
    assert world.made == []


def test_the_turn_cap_still_holds_under_the_limit(world):
    t = ask_turn(world, auto_usd=2.0, budget=TurnBudget(usd=0.001))
    out = BY_NAME["synthesize_take"].run(world.wb, t, ARGS)
    assert out.text.startswith("This step would cost about") and world.made == []


def test_designing_a_voice_under_the_limit_goes_ahead_unless_settings_keep_it_asking(world):
    t = ask_turn(world)
    BY_NAME["design_voice"].run(world.wb, t, {"description": "a warm older woman, slow", "sample_text": ""})
    assert len(world.designed) == 1
    t = ask_turn(world)
    t.ask_before = {**t.ask_before, "design": True}
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["design_voice"].run(world.wb, t, {"description": "a warm older woman, slow", "sample_text": ""})
    assert w.value.options[0].startswith("Design it · $")


# ── meaning is still asked ──────────────────────────────────────────────────

def test_questions_about_meaning_are_still_asked_under_any_limit(world):
    for t in (ask_turn(world, auto_usd=2.0), world.turn(autonomy="draft")):
        with pytest.raises(WaitingForUser) as w:
            BY_NAME["ask"].run(world.wb, t, {"question": "Which line should say it?", "guess": "Line 2",
                                             "options": [{"label": "Line 2", "detail": ""}, {"label": "Line 3", "detail": ""}]})
        assert not w.value.gate and w.value.options == ("Line 2", "Line 3")


def test_a_question_that_leads_to_a_paid_step_carries_its_price_on_the_one_card(world):
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ask"].run(world.wb, ask_turn(world), {
            "question": "Where should the new line go?", "guess": "Voice it here · $0.04", "cost_usd": 0.04,
            "options": [{"label": "Voice it here · $0.04", "detail": "After line 2, over the beach."},
                        {"label": "After line 3", "detail": ""}]})
    assert not w.value.gate and w.value.cost_usd == 0.04
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ask"].run(world.wb, ask_turn(world), {"question": "Which voice?", "guess": "", "cost_usd": 0,
                                                       "options": [{"label": "Ana", "detail": ""}, {"label": "Ben", "detail": ""}]})
    assert w.value.cost_usd is None


def test_a_pick_is_the_approval_for_moving_the_line_it_placed(world):
    from tests.agent.test_tools import _spoken
    _spoken(world)
    args = {"line": 3, "to": 5.0}
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["shift_line"].run(world.wb, ask_turn(world), args)
    assert w.value.options == ("Move it", "Not yet")
    t = replace(ask_turn(world), picked=True)
    BY_NAME["shift_line"].run(world.wb, t, args)
    assert len(world.shifted) == 1
