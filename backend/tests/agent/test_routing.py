"""Cost 1b: a how-do-I question runs on the small model with the read-only tools."""
from types import SimpleNamespace

from app.agent import routing
from tests.agent.conftest import ScriptedClient, reply, text, use
from tests.api.test_endpoints import _agent_on, client, project, reset_state, send  # noqa: F401


class Sorter(ScriptedClient):
    """A scripted agent that also sorts messages: `question` is its answer."""

    def __init__(self, responses, question=True):
        super().__init__(responses)
        self.sorted: list[dict] = []
        self.messages = SimpleNamespace(parse=self._parse)
        self.question = question

    def _parse(self, **params):
        self.sorted.append(params)
        return SimpleNamespace(parsed_output=routing._Sorted(question=self.question),
                               usage=SimpleNamespace(input_tokens=120, output_tokens=8))


def test_only_words_shaped_like_a_question_are_sorted():
    assert routing.looks_like_question("How do I make a vertical version for Reels?")
    assert routing.looks_like_question("can you make it 30% off?")          # sorted by the model, then
    assert not routing.looks_like_question("Make it 30% off")
    assert not routing.looks_like_question("How about warmer")                # no question mark
    assert not routing.is_question(Sorter([]), "m", "Make it 30% off")


def test_a_failed_sort_keeps_the_planner():
    broken = SimpleNamespace(messages=SimpleNamespace(parse=lambda **_: (_ for _ in ()).throw(RuntimeError("down"))))
    assert routing.is_question(broken, "m", "How do I export?") is False


def _routed(monkeypatch, main, question):
    from dataclasses import replace
    scripted = _agent_on(monkeypatch, main, [reply(use("search_help", query="vertical"), stop="tool_use"),
                                             reply(text("Exporting covers it."))])
    sorter = Sorter(scripted.responses, question=question)
    sorter.calls = scripted.calls
    from app.agent.loop import Agent
    monkeypatch.setattr(main, "_agent_instance", Agent(sorter))
    monkeypatch.setattr(main, "settings", replace(main.settings, question_model="claude-haiku-5-5", mock_vendors=False))
    return sorter


def test_a_question_turn_runs_on_the_small_model_with_read_only_tools(client, project, monkeypatch):
    import app.api.main as main
    sorter = _routed(monkeypatch, main, question=True)
    send(client, "How do I make a vertical version for Reels?")
    assert sorter.sorted and sorter.sorted[0]["model"] == "claude-haiku-5-5"
    first = sorter.calls[0]
    assert first["model"] == "claude-haiku-5-5" and first["output_config"] == {"effort": "low"}
    assert {t["name"] for t in first["tools"]} == set(routing.QUESTION_TOOLS)
    assert "betas" not in first
    usage = client.get(f"/videos/{project['video_id']}/usage").json()
    assert any(line["what"] == "routing" for line in usage["lines"])


def test_a_request_put_as_a_question_stays_with_the_planner(client, project, monkeypatch):
    import app.api.main as main
    sorter = _routed(monkeypatch, main, question=False)
    send(client, "Can you make it 30% off?")
    assert sorter.sorted and sorter.calls[0]["model"] == "claude-opus-5-5"
    assert len(sorter.calls[0]["tools"]) > len(routing.QUESTION_TOOLS)
