"""The agent's planning, by Claude (Phase 13).

One structured-output call reads the goal with the whole transcript and
returns the changes that carry it out; a second, smaller call offers a shorter
wording when a line runs long. Effort is low for the shortening (one line) and
medium for the plan (it has to read everything). As with intent reading, the
reply is validated against a schema so the app never parses prose.
"""
from __future__ import annotations

from typing import Literal, Sequence

import anthropic
from pydantic import BaseModel, Field

from app.adapters.claude_intent import IntentConfigError, IntentError, MODEL
from app.orchestrator.intent import Meter
from app.orchestrator.planner import Change, Line, Proposal

MAX_TOKENS = 4000

SYSTEM = """\
You plan edits for a video dialogue editor. The user has a finished video and \
describes, in their own words, how its spoken message should change. You read \
every line of the transcript and decide which lines to change and what each \
should say instead.

The editor can only re-voice dialogue: say new words in a line's place \
("replace") or add a new line right after one ("concatenate", the picture \
holds while it plays). It cannot change visuals, music, or pacing.

Rules:
- `edits` are the changes the goal asks for. Keep each as close to the original \
line as the goal allows; change only what the goal needs. For a replaced line \
write the full new line. Keep each speaker's own way of talking.
- A replaced line is spoken in the same time as the original, with a little \
room to run on; keep new wording about the same length or shorter. An added \
line can be any length but should be short.
- `suggestions` are changes the goal implies but did not name — a word that \
reads oddly once the goal is applied, a line that now contradicts it. Offer at \
most three, and only when genuinely useful. They are not applied unless the \
user adds them.
- `summary` is one or two plain sentences to the user: what you read and what \
you plan, e.g. "I read all 20 lines. Three changes do it."
- `reason` is a few words per change, e.g. "Brand name".
- `line` is the line's number from the transcript.
If the goal cannot be met with dialogue changes, return no edits and say why \
in `summary`.\
"""

SHORTEN_SYSTEM = """\
You shorten one line of video dialogue so it can be spoken in less time. Keep \
its meaning, the speaker's tone and any names or numbers. Reply with the new \
line only.\
"""


class _Edit(BaseModel):
    line: int = Field(description="The transcript line number this change is for.")
    new_text: str = Field(description="The full new line to speak.")
    mix: Literal["replace", "concatenate"]
    reason: str


class _PlanReading(BaseModel):
    summary: str
    edits: list[_Edit]
    suggestions: list[_Edit]


class _Shortening(BaseModel):
    new_text: str


def render_plan_request(goal: str, lines: Sequence[Line], history: Sequence[str]) -> str:
    out = []
    if history:
        out.append("Earlier goals in this project:")
        out += [f"- {h}" for h in history]
        out.append("")
    out.append("Transcript:")
    for line in lines:
        who = f" {line.speaker}:" if line.speaker else ""
        out.append(f"{line.index}. [{line.start:.1f}s]{who} {line.text}")
    out += ["", f"Goal: {goal}"]
    return "\n".join(out)


def to_proposal(reading: _PlanReading, lines: Sequence[Line]) -> Proposal:
    known = {line.index for line in lines}

    def changes(items: list[_Edit]) -> tuple[Change, ...]:
        out = []
        for e in items:
            text = e.new_text.strip().strip('"').strip()
            if e.line in known and text:
                out.append(Change(e.line, text, e.mix, e.reason.strip()))
        return tuple(out)

    return Proposal(
        summary=reading.summary.strip() or "Here's my plan.",
        edits=changes(reading.edits), suggestions=changes(reading.suggestions),
    )


class ClaudePlanner:
    identity = "claude"

    def __init__(
        self, api_key: str, workspace_id: str | None, *, model: str = MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self._model = model

    def _parse(self, system: str, content: str, output_format, effort: str, meter: Meter | None):
        try:
            response = self._client.messages.parse(
                model=self._model, max_tokens=MAX_TOKENS, output_config={"effort": effort},
                system=system, messages=[{"role": "user", "content": content}],
                output_format=output_format,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise IntentError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise IntentConfigError(
                f"Claude refused the request ({exc.status_code}). "
                "Check ANTHROPIC_API_KEY and ANTHROPIC_WORKSPACE_ID."
            ) from None
        if meter is not None and response.usage is not None:
            meter(self._model, response.usage.input_tokens, response.usage.output_tokens)
        return response

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None) -> Proposal:
        response = self._parse(SYSTEM, render_plan_request(goal, lines, history), _PlanReading,
                               "medium", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return Proposal(summary="I can't plan that request.", edits=())
        return to_proposal(response.parsed_output, lines)

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        content = (f'Line: "{text}"\nIt must be spoken in about {share:.0%} of the time it takes now'
                   f" (the original line there was \"{line.text}\").")
        response = self._parse(SHORTEN_SYSTEM, content, _Shortening, "low", meter)
        if response.parsed_output is None:
            return None
        short = response.parsed_output.new_text.strip().strip('"').strip()
        return short if short and short != text else None
