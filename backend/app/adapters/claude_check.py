"""The project check's text pass, by Claude (A2).

One structured-output call over what every video in a project says, on the
smallest model that reads it well (`settings.check_model`), returning the
issues a pattern cannot see (offer names that disagree). Charged through the
meter like every other Claude call, so it lands in Usage under the project.
"""
from __future__ import annotations

import anthropic
from pydantic import BaseModel, Field

from app.adapters.claude_planner import PlannerConfigError, PlannerError
from app.agent.project_check import CHECK_MAX_TOKENS, SYSTEM
from app.orchestrator.meter import Meter


class _Place(BaseModel):
    video_id: str
    quote: str


class _Issue(BaseModel):
    message: str
    places: list[_Place] = Field(default_factory=list)


class _Issues(BaseModel):
    issues: list[_Issue] = Field(default_factory=list)


class ClaudeChecker:
    def __init__(self, api_key: str, workspace_id: str | None, *, model: str,
                 client: anthropic.Anthropic | None = None) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self.model = model

    def read(self, text: str, meter: Meter | None = None) -> list[dict]:
        """The issues, as plain dicts ({message, places: [{video_id, quote}]})."""
        try:
            response = self._client.messages.parse(
                model=self.model, max_tokens=CHECK_MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": text}], output_format=_Issues,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise PlannerError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise PlannerConfigError(f"Claude refused the request ({exc.status_code}).") from None
        if meter is not None and response.usage is not None:
            meter(self.model, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return []
        return [i.model_dump() for i in response.parsed_output.issues]
