"""The tools, one by one: what the model reads, what the thread shows, what is guarded."""
import pytest

from app.domain.models import Selection

from app.agent.guards import TurnBudget, WaitingForUser
from app.agent.tools import BY_NAME, definitions, delivery_of


def test_every_tool_schema_requires_every_property_and_only_the_complex_ones_are_strict():
    from app.agent.tools import MAX_STRICT, MAX_UNIONS, strict_count, union_count
    for d in definitions():
        schema = d["input_schema"]
        assert d["strict"] is False or bool(schema["properties"])   # a tool with no arguments is never strict
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]), d["name"]
    # The API refused 18 union-typed parameters across the tools, 22 strict tools, and 19 strict tools as "the compiled grammar is too large" (live, 2026-10-17/18).
    assert union_count() <= MAX_UNIONS and strict_count() <= MAX_STRICT
    # 20e: the strict ones are the tools with enums, dials or arrays; a one-id tool is plain.
    from app.agent.tools import BY_NAME as by_name
    assert by_name["synthesize_take"].definition()["strict"] and by_name["ask"].definition()["strict"] and by_name["ship"].definition()["strict"]
    assert not by_name["undo_edit"].definition()["strict"] and not by_name["drop_item"].definition()["strict"] and not by_name["read_transcript"].definition()["strict"]


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
    assert "The default is EXAVITQu4vr4xnSDxMaL." in out.text
    assert out.step == "Looked through 2 voices"


def test_a_take_is_placed_by_time_as_a_ready_item_and_costs_what_the_ledger_says(world):
    t = world.turn()
    out = BY_NAME["synthesize_take"].run(world.wb, t, {
        "text": "“Welcome to Goa.”", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
        "direction": "warm and unhurried, a half-smile", "mix": None, "line": None, "item_id": None,
    })
    assert out.step == "Voiced “Welcome to Goa.” with Varsha — warm and unhurried, a half-smile"
    assert out.cost_usd == pytest.approx(0.03)
    assert "Take c1 on i1, Varsha's voice, placed at 0.40 s, over the picture. It sounds right. Fit: nearest of 3 takes. The take itself runs 1.0 s, 3.0 words a second. Spoken with the default model. Cost $0.03." in out.text
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
    assert (item.candidate_id, item.new_text, item.delivery, item.reason) == ("c2", "Welcome to Cavelossim.", "calmer", "slower")


def test_under_check_with_me_a_paid_step_waits_for_the_user_until_they_say_go(world):
    args = {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4,
            "direction": None, "mix": None, "line": None, "item_id": None}
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["synthesize_take"].run(world.wb, world.turn(autonomy="ask"), args)
    assert w.value.question == "Voice “Welcome to Goa.” in Varsha's voice, about $0.00?"
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


def _live_edit(edit_id="e1", text="Where the sand runs wide.", mix="layer", start=0.4, end=7.3):
    from types import SimpleNamespace
    return SimpleNamespace(edit_id=edit_id, reverted=False,
                           plan=SimpleNamespace(selection=Selection(start, end), new_text=text, mix=mix))


def test_ship_anyway_carries_the_users_word_past_the_check(world):
    """20e: the sound check is advice; `anyway` is the user's word, passed to the app as override."""
    t = world.turn()
    BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Wohooo!", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0, "end": 7, "direction": None, "mix": "layer", "line": None, "item_id": None})
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ship"].run(world.wb, world.turn(autonomy="ask"), {"item_ids": [], "anyway": True})
    assert w.value.question == "Ship 1 change and render the video? One did not pass its check."
    out = BY_NAME["ship"].run(world.wb, t, {"item_ids": [], "anyway": True})
    assert out.text.startswith("Shipped 1 change.")
    assert world.shipped == [["i1", "anyway"]]


def test_project_state_lists_what_is_in_the_video_and_undo_edit_takes_one_out(world):
    """20e: shipped edits are visible to the agent, layers stack, and undo_edit is a gated commit."""
    world.live_edits.extend([_live_edit(), _live_edit("e2", "[excited] Where the sand runs WIDE.", start=0.0)])
    state = BY_NAME["project_state"].run(world.wb, world.turn(), {}).text
    assert "In the video already (shipped; undo_edit takes one out):" in state
    assert "- e1 at 0.4–7.3 s: “Where the sand runs wide.” — layered over the picture and sound" in state
    assert "- e2 at 0.0–7.3 s" in state
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["undo_edit"].run(world.wb, world.turn(autonomy="ask"), {"edit_id": "e1"})
    assert (w.value.question, w.value.options) == ("Take e1 (“Where the sand runs wide.”) back out of the video?", ("Undo it", "Keep it"))
    out = BY_NAME["undo_edit"].run(world.wb, world.turn(), {"edit_id": "e1"})
    assert out.text.startswith("e1 is undone: the video no longer carries “Where the sand runs wide.”")
    assert out.step == "Undid e1 (“Where the sand runs wide.”)"
    assert world.undone == ["e1"]
    assert "- e1 at" not in BY_NAME["project_state"].run(world.wb, world.turn(), {}).text
    assert BY_NAME["undo_edit"].run(world.wb, world.turn(), {"edit_id": "e1"}).text.startswith("There is no live edit e1")


def test_a_background_layer_is_voiced_under_the_words_and_levels_change_without_voicing_again(world):
    """20g: `level: background` mixes a layer 12 dB under; set_level moves a proposal or a shipped line between the two."""
    t = world.turn()
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "[shouting] Woohoo!", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0, "end": 7,
                                                       "direction": None, "mix": "layer", "line": None, "item_id": None, "level": "background"})
    assert world.made[-1]["level_db"] == -12.0 and out.step.startswith("Voiced")
    plain = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0, "end": 2,
                                                         "direction": None, "mix": "layer", "line": None, "item_id": None})
    assert world.made[-1]["level_db"] is None and plain.step.startswith("Voiced")
    # A proposal: the item follows the releveled take.
    out = BY_NAME["set_level"].run(world.wb, t, {"item_id": "i2", "edit_id": "", "level": "background"})
    assert out.step == "Set i2 to background" and world.leveled[-1][1] == -12.0
    assert world.repo.get_plan("p1", "plan1").item("i2").candidate_id.endswith("L")
    # A line in the video: gated under Check with me, then releveled by its edit.
    world.live_edits.append(_live_edit("e9", "Woohoo!", start=0.0, end=7.0))
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["set_level"].run(world.wb, world.turn(autonomy="ask"), {"item_id": "", "edit_id": "e9", "level": "foreground"})
    assert w.value.question == "Mix e9 as foreground (+0 dB)?"
    out = BY_NAME["set_level"].run(world.wb, t, {"item_id": "", "edit_id": "e9", "level": "foreground"})
    assert out.text.startswith("e9 is foreground now (+0 dB) as edit e9L")
    assert BY_NAME["set_level"].run(world.wb, t, {"item_id": "", "edit_id": "nope", "level": "background"}).text.startswith("There is no live edit nope")
    assert BY_NAME["set_level"].run(world.wb, t, {"item_id": "", "edit_id": "", "level": "background"}).text.startswith("Name an item_id")


def test_the_users_own_voices_are_listed_as_theirs_and_named_on_a_take(world):
    """20i: list_voices ends with the user's uploaded voices; a take in one is named by it."""
    from dataclasses import replace
    wb = replace(world.wb, mine=lambda owner: [{"voice_id": "MINE1", "name": "Me", "seconds": 12.0}])
    out = BY_NAME["list_voices"].run(wb, world.turn(), {})
    assert "The user's own voices (uploaded by them; \"my voice\" means one of these):" in out.text
    assert "- MINE1 · Me · yours, 12 s of reference" in out.text
    assert out.step == "Looked through 5 voices" or out.step.startswith("Looked through")
    take = BY_NAME["synthesize_take"].run(wb, world.turn(), {"text": "Hello.", "voice_id": "MINE1", "start": 0, "end": 2,
                                                                   "direction": None, "mix": "layer", "line": None, "item_id": None})
    assert take.step == 'Voiced “Hello.” with Me' and "Me's voice" in take.text


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


def test_voicing_a_placed_item_again_with_a_new_span_moves_it(world):
    t = world.turn()
    BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 4.96, "end": 5.6,
                                                 "direction": None, "mix": None, "line": None, "item_id": None})
    out = BY_NAME["synthesize_take"].run(world.wb, t, {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 7.3,
                                                       "direction": "slow", "mix": None, "line": None, "item_id": "i1"})
    assert "The item moved to the new span." in out.text
    [item] = world.repo.get_plan("p1", "plan1").items
    assert (item.selection.start, item.selection.end, item.candidate_id, item.new_text) == (0.4, 7.3, "c2", "Welcome to Goa.")
    assert (world.made[1]["selection"].start, world.made[1]["selection"].end) == (0.4, 7.3)


# ── 20b: expression and voices made for the clip ──────────────────────────────

def _take(world, t, **over):
    args = {"text": "Welcome to Goa.", "voice_id": "kL06KYMvPY56NluIQ72m", "start": 0.4, "end": 2.4, "direction": "",
            "mix": "layer", "line": None, "item_id": "", "model": "default", "stability": None, "style": None, "speed": None, "similarity": None}
    args.update(over)
    return BY_NAME["synthesize_take"].run(world.wb, t, args)


def test_the_models_settings_and_model_reach_the_pipeline_and_tags_pick_v4(world):
    t = world.turn()
    out = _take(world, t, text="[sighs] Welcome to Goa.", stability=0.3, speed=0.9)
    assert world.made[0]["model"] == "v4" and world.made[0]["voice_settings"] == {"stability": 0.3, "speed": 0.9}
    assert "Spoken with v4, stability 0.3, speed 0.9." in out.text
    _take(world, t, model="v2")
    assert world.made[1]["model"] == "v2" and world.made[1]["voice_settings"] is None
    _take(world, t, model="v3")
    assert world.made[2]["model"] == "v3"


def test_designing_a_voice_is_gated_costed_and_leaves_previews_the_user_can_hear(world):
    t = world.turn("ask")
    args = {"description": "An Indian woman near fifty, unhurried, a smile in the voice", "sample_text": None}
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["design_voice"].run(world.wb, t, args)
    assert w.value.question == "Design a voice from “An Indian woman near fifty, unhurried, a smile in the voice” — three previews to hear, about $0.10?"
    assert w.value.gate is True and world.designed == []
    out = BY_NAME["design_voice"].run(world.wb, world.turn("ask", approved=True), args)
    assert world.designed == [{"description": args["description"], "text": None}]
    assert out.step == "Designed a voice from “An Indian woman near fifty, unhurried, a smile in the vo…” — 3 previews to hear"
    assert out.cost_usd == pytest.approx(0.105)
    assert "preview 1: g1 (21 s); preview 2: g2 (22 s); preview 3: g3 (23 s)" in out.text
    assert "You cannot hear them" in out.text and "3 of 30 voice slots are used." in out.text
    # the previews are kept as audio the user can play, and handed to the loop as a card (shown after the step)
    assert [a[2] for a in world.audio] == ["mp3", "mp3", "mp3"]
    assert out.card["text"] == "3 voices designed from “An Indian woman near fifty, unhurried, a smile in the voice”"
    assert out.card["data"]["previews"][1] == {"n": 2, "generated_voice_id": "g2", "sha256": "a" * 63 + "2", "duration": 22.0}
    assert set(world.repo.settings("p1")["designs"]) == {"g1", "g2", "g3"}


def test_a_short_sample_text_and_the_turns_cap_are_refused_in_a_sentence(world):
    out = BY_NAME["design_voice"].run(world.wb, world.turn(), {"description": "a man", "sample_text": "Too short."})
    assert out.text.startswith("A sample text needs at least 100 characters")
    out = BY_NAME["design_voice"].run(world.wb, world.turn(budget=TurnBudget(usd=0.05)), {"description": "a man", "sample_text": None})
    assert out.text.startswith("This step would cost about $0.10; the turn's cap is $0.05")
    assert world.designed == []


def test_a_preview_is_kept_as_a_named_voice_and_only_a_preview_of_this_clip(world):
    t = world.turn()
    out = BY_NAME["save_voice"].run(world.wb, t, {"generated_voice_id": "g2", "name": "Dusk"})
    assert out.text == "g2 is not a preview of this project; design_voice gives the ids."
    BY_NAME["design_voice"].run(world.wb, t, {"description": "an older woman", "sample_text": None})
    out = BY_NAME["save_voice"].run(world.wb, t, {"generated_voice_id": "g2", "name": "  Dusk  "})
    assert world.saved == [("g2", "Dusk", "an older woman")]
    assert out.step == "Kept preview 2 as “Dusk”"
    assert out.text == "Saved preview 2 as “Dusk” (NEWVOICEg2); it is in the catalogue now and can speak a line. 3 of 30 voice slots are used."
    assert world.repo.settings("p1")["made_voices"][0]["voice_id"] == "NEWVOICEg2"


def test_a_library_voice_is_added_by_its_ids_and_a_made_voice_deletes_only_after_a_yes(world):
    t = world.turn()
    out = BY_NAME["add_voice_from_library"].run(world.wb, t, {"voice_id": "LIB", "owner_id": "OWN", "name": "Riya"})
    assert world.added == [("OWN", "LIB", "Riya")] and out.step == "Added Riya from the voice library"
    assert BY_NAME["delete_voice"].run(world.wb, t, {"voice_id": "EXAVITQu4vr4xnSDxMaL"}).text.endswith("only those can be deleted here.")
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["delete_voice"].run(world.wb, t, {"voice_id": "LIB"})
    assert (w.value.question, w.value.options) == ("Delete the voice “Riya” from the account?", ("Delete it", "Keep it"))
    out = BY_NAME["delete_voice"].run(world.wb, world.turn(commit_approved=True), {"voice_id": "LIB"})
    assert world.deleted == ["LIB"] and out.step == "Deleted the voice “Riya”"
    assert world.repo.settings("p1")["made_voices"] == []


def test_measure_reads_a_takes_full_report(world):
    t = world.turn()
    _take(world, t, model="v3", stability=0.5, direction="wistful")
    out = BY_NAME["measure"].run(world.wb, t, {"candidate_id": "c1"})
    assert out.text == ("Take c1: passed the sound check. Runs 1.00 s; 3 words, 3.0 a second. Fit: nearest of 3 takes. "
                        "Spoken with v3, stability 0.5.")
    assert BY_NAME["measure"].run(world.wb, t, {"candidate_id": "c9"}).text == "There is no take c9."


# ── 20c: speech clips ─────────────────────────────────────────────────────────

def _spoken(world):
    """Two speakers and three lines, as read_transcript would show them."""
    from types import SimpleNamespace as NS
    world.speakers[:] = [NS(label="A", name="Priya", voice_id=None, clone_voice_id=None),
                         NS(label="B", name="Mute", voice_id=None, clone_voice_id=None)]
    world.lines[:] = [NS(index=1, start=0.5, end=2.0, speaker="Priya", text="Get 20% off today only.", syllables=7, budget=9),
                      NS(index=2, start=2.4, end=3.1, speaker="Mute", text="Hm.", syllables=1, budget=2),
                      NS(index=3, start=4.0, end=6.0, speaker="Priya", text="Come to Bhaji Cam.", syllables=5, budget=7)]
    world.record.transcript.__class__  # the fake pipeline never reads words
    return world


def test_the_transcript_names_the_speakers_and_a_replacement_with_no_voice_speaks_in_their_own(world, monkeypatch):
    _spoken(world)
    monkeypatch.setattr("app.agent.tools._statements", lambda record: [type("S", (), {"start": 0.5, "speaker": "A"})(), type("S", (), {"start": 4.0, "speaker": "A"})()])
    read = BY_NAME["read_transcript"].run(world.wb, world.turn(), {})
    assert "1. [0.5–2.0] Priya: Get 20% off today only.  (7 syl now, up to 9 fit)" in read.text
    assert read.text.endswith("Speakers: Priya (A); Mute (B). A replacement in a speaker's line speaks in their own voice when voice_id is empty.")
    t = world.turn("ask")
    with pytest.raises(WaitingForUser) as w:
        _take(world, t, text="Get 30% off today only.", voice_id="", line=1, start=None, end=None)
    assert w.value.question == "Voice “Get 30% off today only.” in Priya's own voice, about $0.01?"
    assert world.cloned == []                                   # nothing is cloned before the yes
    out = _take(world, world.turn("ask", approved=True), text="Get 30% off today only.", voice_id="", line=1, start=None, end=None)
    assert world.cloned == [("A", "EXAVITQu4vr4xnSDxMaL")] and world.made[0]["voice_id"] == "CLONEA"
    assert out.text.startswith("Take c1 on i1, Priya's own voice, at 0.50–2.00 s (1.50 s slot).")
    assert world.made[0]["fit"] is None and world.made[0]["flex_max"] is None      # a replacement may flex by default
    assert out.step == "Voiced “Get 30% off today only.” with Priya's own voice"


def test_when_the_speaker_cannot_be_cloned_the_take_says_so_and_uses_the_default(world, monkeypatch):
    _spoken(world)
    monkeypatch.setattr("app.agent.tools._statements", lambda record: [type("S", (), {"start": 2.4, "speaker": "B"})()])
    out = _take(world, world.turn(), text="Oh.", voice_id="", line=2, start=None, end=None)
    assert world.made[0]["voice_id"] == "EXAVITQu4vr4xnSDxMaL"
    assert world.made[0]["voice_notes"] == ("Stock voice: only 3.0 s of Mute's voice, 10 s needed to clone it.",)
    assert "Take c1 on i1, Sarah's voice" in out.text and "Stock voice: only 3.0 s of Mute's voice" in out.text


def test_fit_and_picture_reach_the_pipeline(world):
    _take(world, world.turn(), fit="natural", picture="may flex")
    assert (world.made[0]["fit"], world.made[0]["flex_max"]) == ("start", None)
    _take(world, world.turn(), fit="stretch", picture="as shot")
    assert (world.made[1]["fit"], world.made[1]["flex_max"]) == ("stretch", 1.0)
    _take(world, world.turn())                                  # a placed line: the picture as shot
    assert (world.made[2]["fit"], world.made[2]["flex_max"]) == (None, 1.0)


def test_clone_speaker_asks_then_makes_the_voice_and_says_when_it_cannot(world):
    _spoken(world)
    t = world.turn("ask")
    assert BY_NAME["clone_speaker"].run(world.wb, t, {"speaker": "Ravi"}).text == "There is no speaker called 'Ravi'. The speakers are: Priya (A), Mute (B)."
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["clone_speaker"].run(world.wb, t, {"speaker": "priya"})
    assert w.value.question.startswith("Clone Priya's voice from their own speech") and w.value.options == ("Clone it", "Not yet")
    out = BY_NAME["clone_speaker"].run(world.wb, world.turn("ask", commit_approved=True), {"speaker": "A"})
    assert out.step == "Cloned Priya's voice from their own speech" and "CLONEA" in out.text
    assert BY_NAME["clone_speaker"].run(world.wb, world.turn(), {"speaker": "Priya"}).text.startswith("Priya's own voice is already made (CLONEA)")
    out = BY_NAME["clone_speaker"].run(world.wb, world.turn(), {"speaker": "Mute"})
    assert out.step == "Could not clone Mute's voice" and "only 3.0 s" in out.text
    # A voice picked by hand would win over the clone (15a): cloning on purpose clears the pick first.
    world.speakers[0].voice_id, world.speakers[0].clone_voice_id = "EXAVITQu4vr4xnSDxMaL", None
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["clone_speaker"].run(world.wb, world.turn("ask"), {"speaker": "Priya"})
    assert w.value.question.endswith("Sarah was picked for them by hand; their own voice replaces it.")
    BY_NAME["clone_speaker"].run(world.wb, world.turn(), {"speaker": "Priya"})
    assert world.repo.speakers("p1") == [] or all(s.voice_id is None for s in world.repo.speakers("p1"))


def test_a_take_is_one_take_the_retry_being_voltages_own(world):
    _take(world, world.turn())
    assert world.made[0]["max_regenerations"] == 0


def test_remove_is_a_proposal_and_shift_a_gated_commit_on_a_transcript_line(world):
    _spoken(world)
    t = world.turn("ask")
    assert BY_NAME["remove_line"].run(world.wb, t, {"line": 9}).text == "There is no line 9."
    # 20e: a removal is proposed like a take, under either autonomy; ship is the gate.
    out = BY_NAME["remove_line"].run(world.wb, t, {"line": 2})
    assert world.removed == [(2.4, 3.1)] and out.step == "Proposed removing line 2 (“Hm.”)"
    assert out.text.startswith("Line 2 is proposed removed (2.40–3.10 s; item i-rm)")
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["shift_line"].run(world.wb, t, {"line": 3, "to": 5.0})
    assert w.value.options == ("Move it", "Not yet")
    out = BY_NAME["shift_line"].run(world.wb, world.turn(), {"line": 3, "to": 5.0})
    assert world.shifted == [(4.0, 6.0, 5.0)] and out.step == "Moved line 3 to 5.00 s"


def test_move_item_places_the_same_take_elsewhere(world):
    t = world.turn()
    _take(world, t)
    assert BY_NAME["move_item"].run(world.wb, t, {"item_id": "i9", "start": 3.0}).text == "There is no voiced item i9."
    out = BY_NAME["move_item"].run(world.wb, t, {"item_id": "i1", "start": 3.0})
    assert world.moved == [("c1", 3.0)] and out.step == "Moved i1 to 3.00 s"
    [item] = world.repo.get_plan("p1", "plan1").items
    assert (item.candidate_id, item.selection.start, item.selection.end) == ("c1m", 3.0, 5.0)
