"""The tools, one by one: what the model reads, what the thread shows, what is guarded."""
import pytest

from app.agent.guards import TurnBudget, WaitingForUser
from app.agent.tools import BY_NAME, definitions, delivery_of


def test_every_tool_has_a_strict_schema_with_every_property_required():
    for d in definitions():
        assert d["strict"] is True
        schema = d["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]), d["name"]


def test_a_silent_clip_reads_as_no_speech_and_the_whole_clip_as_room(world):
    t = world.turn()
    read = BY_NAME["read_transcript"].run(world.wb, t, {})
    assert read.text.startswith("No one speaks in this clip. It is 7.5 s")
    assert read.step == "Listened — no one speaks"
    room = BY_NAME["find_room"].run(world.wb, t, {})
    assert "0.0–7.5 s with no speech" in room.text
    heard = BY_NAME["hear"].run(world.wb, t, {"start": 0, "end": 3})
    assert heard.text == "0.0–3.0 s: no speech; background at -40 dBFS."


def test_voices_are_listed_with_the_default_named(world):
    out = BY_NAME["list_voices"].run(world.wb, world.turn(), {})
    assert "- kL06KYMvPY56NluIQ72m · Varsha · female, indian, middle aged · Warm and Clear" in out.text
    assert out.text.endswith("The default is EXAVITQu4vr4xnSDxMaL.")
    assert out.step == "Looked through 2 voices"


def test_a_take_is_placed_by_time_as_a_ready_item_and_costs_what_the_ledger_says(world):
    t = world.turn()
    out = BY_NAME["synthesize_take"].run(world.wb, t, {
        "text": "“Welcome to Goa.”", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
        "direction": "warm and unhurried, a half-smile", "mix": None, "line": None, "item_id": None,
    })
    assert out.step == "Voiced “Welcome to Goa.” with Varsha — warm and unhurried, a half-smile"
    assert out.cost_usd == pytest.approx(0.03)
    assert "Take c1 on i1, Varsha's voice, at 0.40–2.40 s (2.00 s). It sounds right. Fit: nearest of 3 takes. 3.0 words a second. Cost $0.03." in out.text
    assert world.made[0]["mix"] == "layer" and world.made[0]["delivery"] == "calmer"   # "unhurried" wins
    [item] = world.repo.get_plan("p1", "plan1").items
    assert (item.status, item.candidate_id, item.new_text, item.old_text, item.mix) == ("ready", "c1", "Welcome to Goa.", "", "layer")
    assert t.takes == ["c1"]


def test_voicing_the_same_item_again_replaces_its_take_and_keep_take_puts_one_back(world):
    t = world.turn()
    BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
                                                 "direction": None, "mix": None, "line": None, "item_id": None})
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome to Cavelossim.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": None, "end": None,
                                                       "direction": "slower", "mix": None, "line": None, "item_id": "i1"})
    assert "Take c2 on i1" in out.text
    [item] = world.repo.get_plan("p1", "plan1").items
    assert (item.candidate_id, item.new_text, item.delivery) == ("c2", "Welcome to Cavelossim.", "calmer")


def test_under_check_with_me_a_paid_step_waits_for_the_user_until_they_say_go(world):
    args = {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
            "direction": None, "mix": None, "line": None, "item_id": None}
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["synthesize_take"].run(world.wb, world.turn(autonomy="ask"), args)
    assert w.value.question == "Voice “Welcome to Goa.” with Varsha's voice, about $0.00?"
    assert w.value.options == ("Go ahead", "Not yet")
    assert world.made == []
    BY_NAME["synthesize_take"].run(world.wb, world.turn(autonomy="ask", approved=True), args)
    assert len(world.made) == 1


def test_the_turns_money_cap_refuses_in_a_sentence_instead_of_spending(world):
    t = world.turn(budget=TurnBudget(usd=0.01))
    world.ledger.record("p1", "elevenlabs", "take", 10, "characters", 0.01)
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "A long line that costs more than a cent to voice, surely.", "voice_id": "kL06KYMvPY56NluIQ72m",
                                                       "start": 0, "end": 3, "direction": None, "mix": None, "line": None, "item_id": None})
    assert out.text.startswith("This step would cost about $0.02; the turn's cap is $0.01 and $0.01 is spent.")
    assert world.made == []


def test_an_unknown_voice_or_an_empty_span_is_said_not_spent(world):
    t = world.turn()
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Hi", "voice_id": "nobody", "start": 0, "end": 1, "direction": None, "mix": None, "line": None, "item_id": None})
    assert "not a voice in the catalogue" in out.text
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Hi", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 3, "end": 3, "direction": None, "mix": None, "line": None, "item_id": None})
    assert out.text == "That span is empty; the clip is 7.5 s long."
    assert world.made == []


def test_ship_sends_the_voiced_lines_and_waits_under_check_with_me(world):
    t = world.turn()
    BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0, "end": 2, "direction": None, "mix": None, "line": None, "item_id": None})
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ship"].run(world.wb, world.turn(autonomy="ask"), {"item_ids": None})
    assert (w.value.question, w.value.options) == ("Ship 1 change and render the video?", ("Ship it", "Not yet"))
    out = BY_NAME["ship"].run(world.wb, t, {"item_ids": None})
    assert out.text == "Shipped 1 change. The edited video is rendered; the user can download it from the top bar."
    assert world.shipped == [["i1"]]
    again = BY_NAME["ship"].run(world.wb, t, {"item_ids": None})
    assert again.text.startswith("Nothing is ready to ship")


def test_ask_ends_the_turn_with_options_and_a_guess(world):
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ask"].run(world.wb, world.turn(), {"question": "Name the beach?", "options": ["Yes, Cavelossim", "Stay general"], "guess": "Stay general"})
    assert (w.value.question, w.value.options, w.value.guess) == ("Name the beach?", ("Yes, Cavelossim", "Stay general"), "Stay general")
    out = BY_NAME["ask"].run(world.wb, world.turn(), {"question": "?", "options": ["only one"], "guess": None})
    assert out.text == "Give two or three options to choose from."


def test_direction_words_map_to_the_deliveries_the_adapter_knows():
    assert delivery_of("warm and unhurried") == "calmer"      # unhurried wins: calmer is checked before warmer
    assert delivery_of("a warm smile") == "warmer"
    assert delivery_of("brisk, confident") == "firmer"
    assert delivery_of("like a secret") == "like a secret"
    assert delivery_of(None) is None
