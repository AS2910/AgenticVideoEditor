"""One turn of Voltage (Phase 20a): the model, the tools, the caps.

A manual loop over `client.beta.messages.create`, because the harness must
own three things the runner does not: the thread is persisted as the model
saw it (append-only, thinking blocks and all), a tool may end the turn with
a question for the user, and every tool call becomes one narrated step. The
SDK recommends gating inside the tool function; `WaitingForUser` is that.
"""
from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import anthropic

from app.agent.context import SYSTEM
from app.agent.guards import TurnStopped, WaitingForUser
from app.agent.tools import BY_NAME, Tool, ToolResult, Turn, Workbench

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
# Betas: a classifier refusal falls through to another model rather than
# failing the turn; old frames are cleared server-side once the thread is
# long (20b: only `look_at_frames` results, the one tool whose results are
# images; the last three looks stay). Clearing counts as no edit for the
# thinking-block check, where a client-side cut would.
BETAS = ("server-side-fallback-2026-07-01", "context-management-2025-06-27", "compact-2026-01-12")
# Past 100k input tokens the server summarises the older thread into a
# `compaction` block (20d); the loop appends every response's content as it
# came, so the block is persisted and replayed like any other.
CONTEXT_MANAGEMENT = {"edits": [{"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 40000},
                                 "keep": {"type": "tool_uses", "value": 3},
                                 "exclude_tools": [n for n in BY_NAME if n != "look_at_frames"]},
                                {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 100000}}]}

# (model, input, output, cache_read, cache_write) tokens of one request.
Meter = Callable[[str, int, int, int, int], None]
# (step, cost_usd, tool name, data); a callback that takes only the first two or three still works.
OnStep = Callable[..., None]


def _narrator(on_step: OnStep | None) -> Callable[[str, float, str, Any], None] | None:
    """`on_step` as a four-argument call. The trace wants the tool behind
    each step and what the step carries (search_help's articles); callers
    written for (step, cost) or (step, cost, tool) keep working."""
    if on_step is None:
        return None
    try:
        params = list(inspect.signature(on_step).parameters.values())
    except (TypeError, ValueError):
        return on_step
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in params):
        return on_step
    if len(positional) == 3:
        return lambda step, cost, tool, data: on_step(step, cost, tool)
    return lambda step, cost, tool, data: on_step(step, cost)


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


def with_cache_point(messages: list[dict]) -> list[dict]:
    """The thread with a cache breakpoint on its last block, so the next
    request (the next step, or the next turn) reads the prefix from the
    cache. A moved marker is not an edit: the blocks are unchanged."""
    if not messages:
        return messages
    last = messages[-1]
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
    if not blocks:
        return messages
    blocks[-1] = {k: v for k, v in blocks[-1].items() if k != "cache_control"} | {"cache_control": {"type": "ephemeral"}}
    return messages[:-1] + [{**last, "content": blocks}]


INTERRUPTED = "Not run: the turn was interrupted before this step finished. Do it again if it is still wanted."


def _blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _unanswered(assistant: dict, following: dict | None) -> list[dict]:
    uses = [b for b in _blocks(assistant) if b.get("type") == "tool_use"]
    if not uses:
        return []
    have = {b.get("tool_use_id") for b in _blocks(following) if b.get("type") == "tool_result"} if following and following.get("role") == "user" else set()
    return [u for u in uses if u["id"] not in have]


def repaired(history: Sequence[dict]) -> list[dict]:
    """The thread with every tool call answered. A turn that died mid-step
    (a restart, a crash) leaves a `tool_use` with no result, and the API
    refuses the thread until it has one; the result goes at the head of the
    message that follows (or a message of its own). Pure, so each turn
    repairs the stored thread the same way and the prefix stays identical."""
    out: list[dict] = []
    for m in history:
        m = dict(m)
        if out and out[-1].get("role") == "assistant":
            missing = _unanswered(out[-1], m)
            if missing:
                fixes = [_result_block(u["id"], ToolResult(INTERRUPTED), True) for u in missing]
                if m.get("role") == "user":
                    m["content"] = fixes + _blocks(m)
                else:
                    out.append({"role": "user", "content": fixes})
        out.append(m)
    return out


def dangling_tool_uses(history: Sequence[dict]) -> list[dict]:
    """Tool calls at the very end of the thread that never got a result."""
    if not history or history[-1].get("role") != "assistant":
        return []
    return _unanswered(history[-1], None)


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

    def _create(self, system: list[dict], messages: list[dict], effort: str | None = None) -> Any:
        params: dict = dict(model=self._model, max_tokens=MAX_TOKENS, system=system, messages=with_cache_point(list(messages)),
                            tools=[t.definition() for t in self._tools], output_config={"effort": effort or self._effort})
        if self._extras:
            params.update(betas=list(BETAS), fallbacks="default", context_management=CONTEXT_MANAGEMENT)
        try:
            return self._client.beta.messages.create(**params)
        except anthropic.BadRequestError as exc:
            if self._extras and any(w in str(exc) for w in ("fallbacks", "beta", "context_management", "anthropic-beta")):
                log.warning("agent extras refused (%s); running without them", str(exc)[:160])
                self._extras = False
                return self._create(system, messages, effort)
            raise

    def run(self, wb: Workbench, turn: Turn, history: list[dict], user_content: list[dict] | str, *,
            meter: Meter | None = None, on_step: OnStep | None = None, on_card: Callable[[str, dict], None] | None = None,
            persist: Callable[[str, Any], None] | None = None, effort: str | None = None) -> Outcome:
        """One turn. `history` is the thread as the model saw it (dicts);
        `persist(role, content)` is called for every message appended."""
        out = Outcome()
        narrate = _narrator(on_step)
        system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
        messages = repaired(history)

        def append(role: str, content: Any) -> None:
            messages.append({"role": role, "content": content})
            if persist:
                persist(role, content)

        # A step the last turn never finished is answered first, in the same
        # message as the user's words, so the thread is whole again.
        left = dangling_tool_uses(messages)
        if left:
            blocks = user_content if isinstance(user_content, list) else [{"type": "text", "text": user_content}]
            user_content = [_result_block(u["id"], ToolResult(INTERRUPTED), True) for u in left] + list(blocks)
        append("user", user_content)
        started = wb.ledger.spent_usd(turn.project_id)
        while True:
            response = self._create(system, messages, effort)
            usage = getattr(response, "usage", None)
            if usage is not None:
                read = getattr(usage, "cache_read_input_tokens", 0) or 0
                wrote = getattr(usage, "cache_creation_input_tokens", 0) or 0
                log.info("agent request: input %d, cache read %d, cache write %d, output %d, stop %s",
                         usage.input_tokens, read, wrote, usage.output_tokens, getattr(response, "stop_reason", "?"))
                if meter is not None:
                    meter(self._model, usage.input_tokens, usage.output_tokens, read, wrote)
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
                    if narrate:
                        narrate(result.step, result.cost_usd, use["name"], result.data)
                if result.card and on_card:
                    on_card(result.card["text"], result.card["data"])
            append("user", results)
            if isinstance(ended, WaitingForUser):
                out.question = {"text": ended.question, "options": list(ended.options), "guess": ended.guess, "gate": ended.gate,
                                "cost_usd": ended.cost_usd}
                out.reply = _text_of(content)
                break
            if isinstance(ended, TurnStopped):
                out.reply = _text_of(content) or str(ended)
                out.stopped = str(ended)
                break
        out.spent_usd = max(0.0, wb.ledger.spent_usd(turn.project_id) - started)
        return out
