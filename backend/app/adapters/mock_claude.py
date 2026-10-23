"""A stand-in for Claude, for the launch rehearsal (AVE_MOCK_VENDORS=1).

Nothing leaves the machine. It answers the two ways the app calls Claude:

- `messages.parse` (the planner's look, read, understand, shorten): no parsed
  output, so each read falls back to its plain answer ("3 lines.").
- `beta.messages.create` (Voltage's turn): one scripted move per turn. With
  no tool result yet in the turn it places a short new line over the picture
  (`synthesize_take`, a layer from 0.3 s, up to 2 s, inside the clip): a real proposal the user can
  add. After the tool's answer it ends the turn with one sentence.

Each call waits like the real one (AVE_MOCK_CLAUDE_SECONDS, default "1-3")
and reports token counts close to a real turn's, so the ledger and the load
test see realistic numbers. Refused in production (app/config.py).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from types import SimpleNamespace
from typing import Any

LINE = "Fresh every morning."
# A real turn's first call reads the opening view (~9k tokens in, mostly cached
# after the first); its last call is short. Close to the eval's turns.
FIRST_USAGE = dict(input_tokens=9200, output_tokens=420, cache_read_input_tokens=0, cache_creation_input_tokens=0)
LAST_USAGE = dict(input_tokens=600, output_tokens=90, cache_read_input_tokens=9400, cache_creation_input_tokens=0)


def seconds_range(name: str, default: str) -> tuple[float, float]:
    """"2-6" -> (2.0, 6.0); "0" -> (0, 0)."""
    for raw in ((os.environ.get(name) or "").strip(), default):
        lo, _, hi = raw.partition("-")
        try:
            a = float(lo)
            b = float(hi) if hi else a
        except ValueError:
            continue
        return (min(a, b), max(a, b))
    return (0.0, 0.0)


def wait(name: str, default: str) -> float:
    lo, hi = seconds_range(name, default)
    took = random.uniform(lo, hi) if hi > 0 else 0.0
    if took:
        time.sleep(took)
    return took


def _blocks(message: dict) -> list:
    content = message.get("content")
    return content if isinstance(content, list) else [{"type": "text", "text": content or ""}]


def _kind(block: Any) -> str | None:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


CLIP = re.compile(r"The clip: .*?, (\d+(?:\.\d+)?) s, ")


def span_for(messages: list) -> tuple[float, float]:
    """Where the line goes: from 0.3 s, up to 2 s long, inside the clip the opening view names."""
    duration = None
    for m in messages:
        found = CLIP.search(json.dumps(m.get("content"), ensure_ascii=False, default=str))
        if found:
            duration = float(found.group(1))
    if duration is None:
        return (0.5, 2.5)
    start = round(min(0.3, duration * 0.1), 2)
    return (start, round(max(start + 0.5, min(duration - 0.1, start + 2.0)), 2))


class _Messages:
    def parse(self, **params):
        wait("AVE_MOCK_CLAUDE_SECONDS", "1-3")
        return SimpleNamespace(parsed_output=None, stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2400, output_tokens=0))

    def create(self, **params):
        wait("AVE_MOCK_CLAUDE_SECONDS", "1-3")
        messages = params.get("messages") or []
        last = messages[-1] if messages else {"content": ""}
        answered = any(_kind(b) == "tool_result" for b in _blocks(last))
        if not answered:
            start, end = span_for(messages)
            use = {"type": "tool_use", "id": f"toolu_mock_{random.randrange(10**9)}", "name": "synthesize_take",
                   "input": {"text": LINE, "voice_id": "", "direction": "warm and bright", "model": "default",
                             "stability": None, "style": None, "speed": None, "similarity": None,
                             "line": None, "start": start, "end": end, "mix": "layer", "fit": "fit", "picture": "default",
                             "role": "voice", "offset_db": 0, "item_id": "", "beat_at": -1, "key_word": ""}}
            return SimpleNamespace(content=[{"type": "text", "text": "I will place a short line over the opening."}, use],
                                   stop_reason="tool_use", usage=SimpleNamespace(**FIRST_USAGE))
        return SimpleNamespace(content=[{"type": "text", "text": f"I placed “{LINE}” over the opening. Hear it, then add it if it sounds right."}],
                               stop_reason="end_turn", usage=SimpleNamespace(**LAST_USAGE))


class MockAnthropic:
    """Looks like `anthropic.Anthropic` to the planner and the agent loop."""

    def __init__(self) -> None:
        self.messages = _Messages()
        self.beta = SimpleNamespace(messages=self.messages)
