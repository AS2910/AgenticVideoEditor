"""D2: the learned-style pass, by Claude.

One structured-output call over a project's recent proposal decisions (what
Voltage proposed, what the user added, threw out or rewrote first, and why
when they said), on the cheap model the project check uses
(`settings.check_model`), returning at most ONE line for the brief or one
style rule. Charged through the meter like every other Claude call, so it
lands in Usage under the project.
"""
from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel

from app.adapters.claude_planner import PlannerConfigError, PlannerError
from app.orchestrator.meter import Meter

STYLE_MAX_TOKENS = 1024

SYSTEM = """\
You help a video editor learn how one person likes their lines. You read the \
latest decisions they made on lines Voltage proposed for videos in one \
project: added as proposed, thrown out (with their reason when they gave \
one), or rewritten before adding (the words before and after). You also read \
the project's brief and rules as they stand. Find the one clearest pattern \
that the brief and rules do not already say, and suggest ONE short line that \
would make the next proposals closer to what they want. Choose `kind` "rule" \
for a style rule about how lines are written (length, tone, words to prefer), \
or "brief" for something about the campaign itself (the offer, the audience, \
what to always mention). Write `text` as the line itself, plain and short, in \
the user's own terms, at most 25 words. Write `why` as one plain sentence \
that names what you saw, for example "You shortened 4 of the last 10 lines \
before adding them." Return kind "none" when there is no clear pattern or \
the brief and rules already cover it. Never use em dashes; use commas, \
colons or full stops."""


def _effort(model: str) -> dict:
    """Low effort on the models that think by default (Haiku 4.5 takes no effort)."""
    return {} if model.startswith("claude-haiku-4") else {"output_config": {"effort": "low"}}


class StyleSuggestion(BaseModel):
    kind: Literal["brief", "rule", "none"]
    text: str = ""
    why: str = ""


class ClaudeStyleReader:
    def __init__(self, api_key: str, workspace_id: str | None, *, model: str,
                 client: anthropic.Anthropic | None = None) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self.model = model

    def suggest(self, text: str, meter: Meter | None = None) -> dict | None:
        """{kind, text, why} for one suggestion, or None when there is no pattern."""
        try:
            response = self._client.messages.parse(
                model=self.model, max_tokens=STYLE_MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": text}], **_effort(self.model), output_format=StyleSuggestion,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise PlannerError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise PlannerConfigError(f"Claude refused the request ({exc.status_code}).") from None
        if meter is not None and response.usage is not None:
            meter(self.model, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return None
        out = response.parsed_output
        if out.kind == "none" or not out.text.strip():
            return None
        return {"kind": out.kind, "text": out.text.strip(), "why": out.why.strip()}
