"""Free-form edit requests, read by Claude (Phase 8).

One structured-output call per chat message: the reply is validated against
`_Reading`, so the app never parses prose. Effort is low — this is a short
reading task and the user is waiting on it.

The key is not scoped to a workspace, so every request names one
(`anthropic-workspace-id`); without it the API refuses the call.
"""
from __future__ import annotations

from typing import Literal, Sequence

import anthropic
from pydantic import BaseModel, Field

from app.adapters.base import VendorError
from app.domain.models import Intent
from app.errors import NonRetryableError
from app.orchestrator.intent import EditContext, Turn

MODEL = "claude-opus-5"
MAX_TOKENS = 2000

SYSTEM = """\
You read requests in a video dialogue editor. The user has selected a span of \
their video and describes, in their own words, what they want there.

The editor can do exactly one thing: speak a new line of dialogue in that span \
(in a synthetic voice), replacing what is said there, laying it over the \
original sound, or adding it after the selection. It cannot change visuals \
(colours, backgrounds, objects, faces, framing), music, or anything else.

Decide:
- action "speak": the request asks for a line to be said. `new_text` is exactly \
the words to speak — just the spoken words, no quotes or stage directions. For \
a change to what is already said ("say 30% instead of 20%", "make it urgent"), \
write the full new line for the selected words, keeping the rest of their \
wording unless asked to change it.
- action "unsupported": the request is not about speech. `reply` says briefly \
and plainly that this editor only changes spoken dialogue.
- action "clarify": it is about speech but you cannot tell what to say. `reply` \
is one short question.

`mix` — how the line meets the original sound. Set it only when the request \
says so; otherwise null, and the editor will ask:
- "replace": the request replaces what is said or heard there.
- "layer": over / on top of / alongside the existing sound or music.
- "concatenate": after the selection / then / at the end of it.
A request to change existing words is "replace".

Use the conversation so far to resolve follow-ups like "now say it louder" or \
"no, the other one".\
"""


class _Reading(BaseModel):
    action: Literal["speak", "unsupported", "clarify"]
    new_text: str | None = Field(description="The words to speak, for action 'speak'.")
    mix: Literal["replace", "layer", "concatenate"] | None
    reply: str | None = Field(description="What to tell the user, for 'unsupported' or 'clarify'.")


class IntentError(VendorError):
    """Claude could not be reached or is overloaded; worth retrying."""


class IntentConfigError(NonRetryableError):
    """Claude refused the request itself: key, workspace, or a bad parameter."""


def render_request(prompt: str, history: Sequence[Turn], context: EditContext) -> str:
    sel = context.selection
    lines = []
    if history:
        lines.append("Conversation so far:")
        lines += [f"{t.role}: {t.text}" for t in history]
        lines.append("")
    lines.append(f"Video length: {context.duration:.2f}s")
    lines.append(f"Selection: {sel.start:.2f}s–{sel.end:.2f}s ({sel.end - sel.start:.2f}s)")
    lines.append(f'Words in the selection: "{context.selected}"' if context.has_speech
                 else "Words in the selection: none — no speech there")
    if context.before:
        lines.append(f'Words just before: "{context.before}"')
    if context.after:
        lines.append(f'Words just after: "{context.after}"')
    lines += ["", f"Request: {prompt}"]
    return "\n".join(lines)


def to_intent(reading: _Reading) -> Intent:
    if reading.action == "speak":
        text = (reading.new_text or "").strip().strip('"').strip()
        if not text:
            return Intent(action="clarify", reply="What should be said there?")
        return Intent(action="speak", new_text=text, mix=reading.mix)
    fallback = ("This editor only changes spoken dialogue." if reading.action == "unsupported"
                else "Could you say what should be said there?")
    return Intent(action=reading.action, reply=(reading.reply or "").strip() or fallback)


class ClaudeInterpreter:
    identity = "claude"

    def __init__(
        self, api_key: str, workspace_id: str | None, *, model: str = MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self._model = model

    def interpret(self, prompt: str, history: Sequence[Turn], context: EditContext) -> Intent:
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=MAX_TOKENS,
                output_config={"effort": "low"},
                system=SYSTEM,
                messages=[{"role": "user", "content": render_request(prompt, history, context)}],
                output_format=_Reading,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise IntentError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise IntentConfigError(
                f"Claude refused the request ({exc.status_code}). "
                "Check ANTHROPIC_API_KEY and ANTHROPIC_WORKSPACE_ID."
            ) from None

        if response.stop_reason == "refusal":
            return Intent(action="unsupported", reply="I can't help with that request.")
        if response.parsed_output is None:
            raise IntentConfigError(f"Claude's reply could not be read (stop: {response.stop_reason}).")
        return to_intent(response.parsed_output)
