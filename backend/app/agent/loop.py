"""One turn of Voltage (Phase 20a): the model, the tools, the caps.

A manual loop over `client.beta.messages.create`, because the harness must
own three things the runner does not: the thread is persisted as the model
saw it (append-only, thinking blocks and all), a tool may end the turn with
a question for the user, and every tool call becomes one narrated step. The
SDK recommends gating inside the tool function; `WaitingForUser` is that.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import anthropic

from app.agent.context import SYSTEM
from app.agent.guards import TurnStopped, WaitingForUser
from app.agent.tools import BY_NAME, Tool, ToolResult, Turn, Workbench, definitions

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
# Betas: a classifier refusal falls through to another model rather than
# failing the turn; old tool results (frames) are cleared server-side.
BETAS = ("server-side-fallback-2026-07-01", "context-management-2025-06-27")
CONTEXT_MANAGEMENT = {"edits": [{"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 60000},
                                 "keep": {"type": "tool_uses", "value": 6}}]}

Meter = Callable[[str, int, int], None]
OnStep = Callable[[str, float], None]


@dataclass
class Outcome:
    reply: str = ""
    question: dict | None = None
    steps: list[str] = field(default_factory=list)
    spent_usd: float = 0.0
    calls: int = 0
    stopped: str | None = None          # why the turn ended early, in a sentence


def _dump(block: Any) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return dict(block)


def _text_of(content: Sequence[Any]) -> str:
    parts = []
    for b in content:
        kind = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        if kind == "text":
            parts.append(getattr(b, "text", None) or b.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _result_block(tool_use_id: str, result: ToolResult, is_error: bool = False) -> dict:
    content: Any = result.blocks if result.blocks else result.text
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


class Agent:
    """Runs turns against one Anthropic client. `extras` (betas, fallbacks,
    context management) are dropped after a 400 that names them, so a key or
    model without them still works."""

    def __init__(self, client: anthropic.Anthropic, *, model: str = MODEL, effort: str = "high",
                 tools: Sequence[Tool] | None = None, extras: bool = True) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._tools = list(tools) if tools is not None else list(BY_NAME.values())
        self._by_name = {t.name: t for t in self._tools}
        self._extras = extras

    @property
    def model(self) -> str:
        return self._model

    def _create(self, system: list[dict], messages: list[dict]) -> Any:
        params: dict = dict(model=self._model, max_tokens=MAX_TOKENS, system=system, messages=list(messages),
                            tools=[t.definition() for t in self._tools], output_config={"effort": self._effort})
        if self._extras:
            params.update(betas=list(BETAS), fallbacks="default", context_management=CONTEXT_MANAGEMENT)
        try:
            return self._client.beta.messages.create(**params)
        except anthropic.BadRequestError as exc:
            if self._extras and any(w in str(exc) for w in ("fallbacks", "beta", "context_management", "anthropic-beta")):
                log.warning("agent extras refused (%s); running without them", str(exc)[:160])
                self._extras = False
                return self._create(system, messages)
            raise

    def run(self, wb: Workbench, turn: Turn, history: list[dict], user_content: list[dict] | str, *,
            meter: Meter | None = None, on_step: OnStep | None = None,
            persist: Callable[[str, Any], None] | None = None) -> Outcome:
        """One turn. `history` is the thread as the model saw it (dicts);
        `persist(role, content)` is called for every message appended."""
        out = Outcome()
        system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
        messages = list(history)

        def append(role: str, content: Any) -> None:
            messages.append({"role": role, "content": content})
            if persist:
                persist(role, content)

        append("user", user_content)
        started = wb.ledger.spent_usd(turn.project_id)
        while True:
            response = self._create(system, messages)
            if meter is not None and getattr(response, "usage", None) is not None:
                meter(self._model, response.usage.input_tokens, response.usage.output_tokens)
            content = [_dump(b) for b in response.content]
            append("assistant", content)
            stop = getattr(response, "stop_reason", "end_turn")
            if stop == "refusal":
                out.reply = "I can't help with that one."
                out.stopped = "refusal"
                break
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses or stop in ("end_turn", "max_tokens"):
                if uses and stop == "max_tokens":
                    # The reply was cut mid tool call; answer the calls as not run so the thread stays valid.
                    append("user", [_result_block(u["id"], ToolResult("Not run: the reply was cut short."), True) for u in uses])
                out.reply = _text_of(content) or out.reply
                if stop == "max_tokens":
                    out.stopped = "max_tokens"
                break
            results: list[dict] = []
            ended: WaitingForUser | TurnStopped | None = None
            for use in uses:
                if ended is not None:
                    results.append(_result_block(use["id"], ToolResult("Not run: the turn ended before this step."), True))
                    continue
                tool = self._by_name.get(use["name"])
                if tool is None:
                    results.append(_result_block(use["id"], ToolResult(f"There is no tool called {use['name']}."), True))
                    continue
                try:
                    turn.budget.take_call()
                    out.calls += 1
                    args = use.get("input") or {}
                    if isinstance(args, str):
                        args = json.loads(args)
                    result = tool.run(wb, turn, args)
                except WaitingForUser as w:
                    ended = w
                    results.append(_result_block(use["id"], ToolResult(f"Waiting for the user: {w.question}")))
                    continue
                except TurnStopped as s:
                    ended = s
                    results.append(_result_block(use["id"], ToolResult(str(s))))
                    continue
                except Exception as exc:  # noqa: BLE001 — a tool that breaks is reported to the model, never raised
                    log.exception("tool %s failed", use["name"])
                    results.append(_result_block(use["id"], ToolResult(f"{use['name']} failed: {exc}"), True))
                    continue
                results.append(_result_block(use["id"], result))
                if result.step:
                    out.steps.append(result.step)
                    if on_step:
                        on_step(result.step, result.cost_usd)
            append("user", results)
            if isinstance(ended, WaitingForUser):
                out.question = {"text": ended.question, "options": list(ended.options), "guess": ended.guess, "gate": ended.gate}
                out.reply = _text_of(content)
                break
            if isinstance(ended, TurnStopped):
                out.reply = _text_of(content) or str(ended)
                out.stopped = str(ended)
                break
        out.spent_usd = max(0.0, wb.ledger.spent_usd(turn.project_id) - started)
        return out
