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
    assert all(t["strict"] for t in first["tools"]) and first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "high"} and first["model"] == "claude-opus-5-5"
    assert len(client.calls[2]["messages"]) == 5


def test_a_question_ends_the_turn_with_the_pending_calls_answered_as_not_run(world):
    client = ScriptedClient([
        reply(use("synthesize_take", "a", text="Welcome.", voice_id="kL06KYMvPY56NluIQ72m", start=0, end=2, direction=None, mix=None, line=None, item_id=None),
              use("list_voices", "b"), stop="tool_use"),
    ])
    out, persisted, steps = run(world, client, turn=world.turn(autonomy="ask"))
    assert out.question == {"text": "Voice “Welcome.” with Varsha's voice, about $0.00?", "options": ["Go ahead", "Not yet"], "guess": "Go ahead", "gate": True}
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
