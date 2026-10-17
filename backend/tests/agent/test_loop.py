"""The loop: tools run, steps narrate, the thread is append-only, and a
question or a cap ends the turn cleanly."""
from app.agent.guards import TurnBudget
from app.agent.loop import Agent
from tests.agent.conftest import ScriptedClient, reply, text, use


def run(world, client, turn=None, **kw):
    persisted = []
    steps = []
    agent = Agent(client, extras=kw.pop("extras", True))
    out = agent.run(world.wb, turn or world.turn(), [], "Describe the place in an Indian voice",
                    on_step=lambda s, c: steps.append((s, c)), persist=lambda r, c: persisted.append((r, c)), **kw)
    return out, persisted, steps


def test_a_turn_looks_voices_and_closes_with_a_sentence(world):
    client = ScriptedClient([
        reply(use("read_transcript", "a"), use("list_voices", "b"), stop="tool_use"),
        reply(text("Voicing one line."), use("synthesize_take", "c", text="Welcome to Goa.", voice_id="kL06KYMvPY56NluIQ72m",
                                              start=0.4, end=2.4, direction="warm", mix=None, line=None, item_id=None), stop="tool_use"),
        reply(text("One line over the opening shot, in Varsha's voice. Hear it below.")),
    ])
    out, persisted, steps = run(world, client)
    assert out.reply == "One line over the opening shot, in Varsha's voice. Hear it below."
    assert out.question is None and out.calls == 3
    assert [s for s, _ in steps] == ["Listened — no one speaks", "Looked through 2 voices", "Voiced “Welcome to Goa.” with Varsha — warm"]
    assert steps[-1][1] == 0.03 and out.spent_usd == 0.03
    # The thread as the model saw it: user, assistant, results, assistant, results, assistant.
    assert [r for r, _ in persisted] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    results = persisted[2][1]
    assert [b["tool_use_id"] for b in results] == ["a", "b"] and results[0]["type"] == "tool_result"
    # The request: the system prompt is cached, the tools are strict, extras on.
    first = client.calls[0]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Strict on the tools with enums, dials or arrays; a one-id tool is plain (the API's grammar limit, 20e).
    assert {t["name"] for t in first["tools"] if t["strict"]} == {"search_voice_library", "synthesize_take", "design_voice", "clone_speaker", "shift_line", "ship", "ask"}
    assert first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "high"} and first["model"] == "claude-opus-5-5"
    assert len(client.calls[2]["messages"]) == 5


def test_a_question_ends_the_turn_with_the_pending_calls_answered_as_not_run(world):
    client = ScriptedClient([
        reply(use("synthesize_take", "a", text="Welcome.", voice_id="kL06KYMvPY56NluIQ72m", start=0, end=2, direction=None, mix=None, line=None, item_id=None),
              use("list_voices", "b"), stop="tool_use"),
    ])
    out, persisted, steps = run(world, client, turn=world.turn(autonomy="ask"))
    assert out.question == {"text": "Voice “Welcome.” in Varsha's voice, about $0.00?", "options": ["Go ahead", "Not yet"], "guess": "Go ahead", "gate": True}
    results = persisted[-1][1]
    assert results[0]["content"].startswith("Waiting for the user:")
    assert results[1]["content"] == "Not run: the turn ended before this step." and results[1]["is_error"] is True
    assert steps == [] and world.made == []


def test_the_call_cap_stops_the_turn_and_tells_the_model(world):
    client = ScriptedClient([reply(use("project_state", f"t{i}"), stop="tool_use") for i in range(5)])
    out, persisted, _ = run(world, client, turn=world.turn(budget=TurnBudget(calls=2)))
    assert out.stopped.startswith("This turn has used its 2 steps.")
    assert out.calls == 2 and len(client.calls) == 3


def test_a_tool_that_breaks_is_reported_as_an_error_result_not_raised(world):
    world.wb.voices = lambda: (_ for _ in ()).throw(RuntimeError("vendor down"))
    client = ScriptedClient([reply(use("list_voices", "a"), stop="tool_use"), reply(text("I could not list the voices just now."))])
    out, persisted, _ = run(world, client)
    results = persisted[2][1]
    assert results[0]["is_error"] is True and "vendor down" in results[0]["content"]
    assert out.reply == "I could not list the voices just now."


def test_a_refusal_and_a_cut_reply_end_quietly(world):
    out, _, _ = run(world, ScriptedClient([reply(text("…"), stop="refusal")]))
    assert out.reply == "I can't help with that one." and out.stopped == "refusal"
    out, persisted, _ = run(world, ScriptedClient([reply(text("Half a"), use("list_voices", "a"), stop="max_tokens")]))
    assert out.reply == "Half a" and out.stopped == "max_tokens"
    assert persisted[-1][1][0]["content"] == "Not run: the reply was cut short."


def test_extras_are_dropped_after_a_400_that_names_them(world):
    import anthropic
    import httpx

    class Picky(ScriptedClient):
        def _create(self, **params):
            self.calls.append(params)
            if "fallbacks" in params:
                raise anthropic.BadRequestError("fallbacks: unknown parameter", response=httpx.Response(400, request=httpx.Request("POST", "x")), body=None)
            return super()._create(**params)

    client = Picky([reply(text("Done."))])
    out, _, _ = run(world, client)
    assert out.reply == "Done."
    assert "fallbacks" in client.calls[0] and "fallbacks" not in client.calls[1] and "betas" not in client.calls[1]


def test_the_thread_is_cached_at_its_last_block_and_cache_tokens_are_metered(world):
    from types import SimpleNamespace
    from app.agent.loop import with_cache_point
    r = reply(use("read_transcript", "a"), stop="tool_use")
    r.usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=5000, cache_creation_input_tokens=700)
    client = ScriptedClient([r, reply(text("Done."))])
    metered = []
    run(world, client, meter=lambda *a: metered.append(a))
    # Each request marks the last block of the last message, and nothing else in the thread.
    for call in client.calls:
        sent = call["messages"]
        assert sent[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        marked = [b for m in sent for b in (m["content"] if isinstance(m["content"], list) else []) if "cache_control" in b]
        assert len(marked) == 1
    # The persisted thread carries no marker (a moved marker is not an edit).
    assert metered[0] == ("claude-opus-5-5", 100, 20, 5000, 700)
    assert with_cache_point([]) == []
    assert with_cache_point([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}]


def test_context_editing_clears_only_old_frames():
    from app.agent.loop import CONTEXT_MANAGEMENT
    edit = CONTEXT_MANAGEMENT["edits"][0]
    assert edit["trigger"] == {"type": "input_tokens", "value": 40000} and edit["keep"] == {"type": "tool_uses", "value": 3}
    assert "look_at_frames" not in edit["exclude_tools"] and "synthesize_take" in edit["exclude_tools"]


def test_a_step_the_last_turn_never_finished_is_answered_before_the_users_words(world):
    """A turn that died mid-step (a restart) left a tool_use with no result;
    the next turn answers it as not run, in the same message as the words."""
    history = [{"role": "user", "content": [{"type": "text", "text": "Design a voice"}]},
               {"role": "assistant", "content": [{"type": "text", "text": "Designing."},
                                                 {"type": "tool_use", "id": "lost", "name": "design_voice", "input": {"description": "x", "sample_text": ""}}]}]
    client = ScriptedClient([reply(text("Carrying on."))])
    out = Agent(client).run(world.wb, world.turn(), history, "go")
    assert out.reply == "Carrying on."
    [sent] = client.calls
    last = sent["messages"][-1]
    assert last["role"] == "user" and len(sent["messages"]) == 3
    assert last["content"][0]["type"] == "tool_result" and last["content"][0]["tool_use_id"] == "lost" and last["content"][0]["is_error"]
    assert last["content"][0]["content"].startswith("Not run: the turn was interrupted")
    assert last["content"][1] == {"type": "text", "text": "go", "cache_control": {"type": "ephemeral"}}


def test_a_lost_step_buried_by_later_messages_is_answered_where_it_happened(world):
    """Two failed retries after a dead turn left user messages after the lost
    tool_use; the repair puts its result at the head of the message that follows."""
    from app.agent.loop import repaired
    history = [{"role": "user", "content": [{"type": "text", "text": "Design a voice"}]},
               {"role": "assistant", "content": [{"type": "tool_use", "id": "lost", "name": "design_voice", "input": {}}]},
               {"role": "user", "content": [{"type": "text", "text": "go"}]},
               {"role": "user", "content": "go"}]
    fixed = repaired(history)
    assert fixed[2]["content"][0]["tool_use_id"] == "lost" and fixed[2]["content"][1] == {"type": "text", "text": "go"}
    assert fixed[3] == {"role": "user", "content": "go"} and history[2]["content"][0]["type"] == "text"   # the stored thread is untouched
    # Two assistant messages in a row get a result message between them.
    two = repaired(history[:2] + [{"role": "assistant", "content": [{"type": "text", "text": "Hm."}]}])
    assert two[2]["role"] == "user" and two[2]["content"][0]["tool_use_id"] == "lost" and len(two) == 4
    client = ScriptedClient([reply(text("Carrying on."))])
    out = Agent(client).run(world.wb, world.turn(), history, "go")
    assert out.reply == "Carrying on." and client.calls[0]["messages"][2]["content"][0]["tool_use_id"] == "lost"


def test_a_card_follows_its_step_and_the_turns_effort_goes_in_the_request(world):
    client = ScriptedClient([
        reply(use("design_voice", "d", description="an older woman", sample_text=""), stop="tool_use"),
        reply(text("Which one?")),
    ])
    shown: list[tuple] = []
    out = Agent(client).run(world.wb, world.turn(), [], "design a voice",
                            on_step=lambda s, c: shown.append(("step", s)), on_card=lambda t, d: shown.append(("card", t, len(d["previews"]))),
                            effort="xhigh")
    assert out.reply == "Which one?"
    assert shown == [("step", "Designed a voice from “an older woman” — 3 previews to hear"), ("card", "3 voices designed from “an older woman”", 3)]
    assert all(c["output_config"] == {"effort": "xhigh"} for c in client.calls)
    from app.agent.loop import BETAS, CONTEXT_MANAGEMENT
    assert "compact-2026-01-12" in BETAS and CONTEXT_MANAGEMENT["edits"][1] == {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 100000}}
