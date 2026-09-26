"""Claude intent reader tests. No network: the SDK client is faked."""
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.adapters.base import VendorError
from app.adapters.claude_intent import (
    ClaudeInterpreter, IntentConfigError, _Reading, render_request, to_intent,
)
from app.domain.models import Selection, Transcript, Word
from app.errors import NonRetryableError
from app.orchestrator.intent import Turn, edit_context

CTX = edit_context(
    Transcript(words=(Word("Get", 0.0, 0.4), Word("20%", 0.4, 0.9), Word("off", 0.9, 1.3))),
    Selection(0.4, 1.3), 2.3,
)
SILENT = edit_context(Transcript(words=()), Selection(2.1, 5.9), 8.0)


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def interpreter(result):
    messages = FakeMessages(result)
    return ClaudeInterpreter("k", "wrkspc_x", client=SimpleNamespace(messages=messages)), messages


def parsed(**fields):
    reading = _Reading(**{"new_text": None, "mix": None, "reply": None, **fields})
    return SimpleNamespace(stop_reason="end_turn", parsed_output=reading)


def _status_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_a_spoken_line_comes_back_as_speak():
    reader, messages = interpreter(parsed(action="speak", new_text="Thirsty Thirsty", mix="layer"))
    intent = reader.interpret('Add "Thirsty Thirsty" over the music', [], SILENT)
    assert (intent.action, intent.new_text, intent.mix) == ("speak", "Thirsty Thirsty", "layer")
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"] == {"effort": "low"}


def test_a_visual_request_is_answered_not_attempted():
    reader, _ = interpreter(parsed(action="unsupported", reply="I can only change speech."))
    intent = reader.interpret("make the background white", [], SILENT)
    assert (intent.action, intent.reply) == ("unsupported", "I can only change speech.")


def test_an_empty_line_becomes_a_question():
    assert to_intent(_Reading(action="speak", new_text=' "" ', mix=None, reply=None)).action == "clarify"


def test_a_refusal_is_a_reply_not_an_error():
    reader, _ = interpreter(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    assert reader.interpret("x", [], CTX).action == "unsupported"


def test_the_request_shows_the_selection_and_the_conversation():
    text = render_request("louder", [Turn("user", 'say "hi"'), Turn("assistant", "Done.")], CTX)
    assert 'user: say "hi"' in text and "assistant: Done." in text
    assert 'Words in the selection: "20% off"' in text
    assert 'Words just before: "Get"' in text
    assert "Request: louder" in text


def test_a_selection_without_speech_says_so():
    assert "no speech there" in render_request("x", [], SILENT)


def test_the_workspace_travels_on_every_request():
    reader = ClaudeInterpreter("k", "wrkspc_x")
    assert reader._client.default_headers["anthropic-workspace-id"] == "wrkspc_x"


@pytest.mark.parametrize("error", [
    _status_error(anthropic.RateLimitError, 429),
    _status_error(anthropic.InternalServerError, 500),
    anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
])
def test_transient_failures_are_retryable(error):
    reader, _ = interpreter(error)
    with pytest.raises(VendorError):
        reader.interpret("x", [], CTX)


def test_a_rejected_key_is_not_retried():
    reader, _ = interpreter(_status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(IntentConfigError) as err:
        reader.interpret("x", [], CTX)
    assert isinstance(err.value, NonRetryableError)
    assert "ANTHROPIC_WORKSPACE_ID" in str(err.value)


def test_token_usage_is_reported_to_the_meter():
    result = parsed(action="speak", new_text="hi")
    result.usage = SimpleNamespace(input_tokens=540, output_tokens=75)
    reader, _ = interpreter(result)
    seen = []
    reader.interpret("x", [], CTX, meter=lambda *call: seen.append(call))
    assert seen == [("claude-opus-5", 540, 75)]
