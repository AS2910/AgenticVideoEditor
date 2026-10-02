"""Claude planner tests. No network: the SDK client is faked."""
from types import SimpleNamespace

from app.adapters.claude_planner import (
    ClaudePlanner, _Edit, _PlanReading, _Shortening, render_plan_request, to_proposal,
)
from app.orchestrator.planner import Line

LINES = [
    Line(1, 5.2, 6.9, "Customer", "Hi, I want to buy groceries."),
    Line(2, 7.5, 9.0, "Customer", "Start a live Bajicam session."),
    Line(3, 9.4, 9.9, "Shopkeeper", "Sure, sir."),
]


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def planner(result):
    messages = FakeMessages(result)
    return ClaudePlanner("k", "wrkspc_x", client=SimpleNamespace(messages=messages)), messages


def test_the_request_numbers_every_line_with_its_speaker_and_time():
    text = render_plan_request("Say Bhaji Cam", LINES, ["an earlier goal"])
    assert "2. [7.5s] Customer: Start a live Bajicam session." in text
    assert "Earlier goals in this project:\n- an earlier goal" in text
    assert text.endswith("Goal: Say Bhaji Cam")


def test_a_plan_comes_back_as_edits_and_suggestions_on_known_lines():
    reading = _PlanReading(
        summary="I read all 3 lines. One change does it.",
        edits=[_Edit(line=2, new_text=' "Start a live Bhaji Cam session." ', mix="replace", reason="Brand name")],
        suggestions=[_Edit(line=3, new_text="Sure, sir. Everything is 30% off.", mix="concatenate", reason="The offer"),
                     _Edit(line=9, new_text="nope", mix="replace", reason="no such line")],
    )
    usage = SimpleNamespace(input_tokens=900, output_tokens=120)
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=reading, usage=usage))
    metered = []

    proposal = reader.plan("Say Bhaji Cam", LINES, meter=lambda m, i, o: metered.append((m, i, o)))

    assert proposal.summary == "I read all 3 lines. One change does it."
    assert [(c.line, c.new_text, c.mix) for c in proposal.edits] == [(2, "Start a live Bhaji Cam session.", "replace")]
    assert [c.line for c in proposal.suggestions] == [3]   # the unknown line is dropped
    assert messages.calls[0]["output_config"] == {"effort": "medium"}
    assert metered == [("claude-opus-5", 900, 120)]


def test_a_refusal_plans_nothing():
    reader, _ = planner(SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None))
    assert reader.plan("x", LINES).edits == ()


def test_to_proposal_drops_empty_lines():
    reading = _PlanReading(summary="", edits=[_Edit(line=1, new_text='""', mix="replace", reason="")], suggestions=[])
    assert to_proposal(reading, LINES).edits == ()
    assert to_proposal(reading, LINES).summary == "Here's my plan."


def test_shorten_returns_a_different_shorter_line_or_nothing():
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text='"Two kinds, both on sale."'), usage=None))
    assert reader.shorten("Yes, we have two varieties, all on sale today.", 0.7, LINES[2]) == "Two kinds, both on sale."
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    same, _ = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text="same"), usage=None))
    assert same.shorten("same", 0.7, LINES[2]) is None
