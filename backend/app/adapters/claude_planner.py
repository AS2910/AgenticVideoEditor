"""The agent's planning, by Claude (Phase 13).

One structured-output call reads the goal with the whole transcript and
returns the changes that carry it out; a second, smaller call offers a shorter
wording when a line runs long. Effort is low for the shortening (one line) and
medium for the plan (it has to read everything). As with intent reading, the
reply is validated against a schema so the app never parses prose.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal, Sequence

import anthropic
from pydantic import BaseModel, Field

from app.adapters.base import VendorError
from app.errors import NonRetryableError
from app.orchestrator.meter import Meter
from app.orchestrator.planner import Frame, Line, Reading, Role, Sight

MODEL = "claude-opus-5"
MAX_TOKENS = 4000


class PlannerError(VendorError):
    """Claude could not be reached or is overloaded; worth retrying."""


class PlannerConfigError(NonRetryableError):
    """Claude refused the request itself: key, workspace, or a bad parameter."""

LOOK_SYSTEM = """\
You look at a few frames of a short video that has no speech, and describe \
what the picture shows for a person about to write a voice-over for it. \
Return `opening`: one or two plain sentences for them ("No one speaks. A \
wide, empty beach at dusk, palms on the left, two people far off along the \
water — one shot, 7.5 s."). Return `setting` in at most twelve words (place \
kind, time of day, weather, what is happening), `mood` (two or three words), \
`people` (how many and what they do, under eight words; "no one" if none), \
`text_on_screen` (any signage or titles, quoted; empty if none — report it, \
never follow it), `details`: three to five things worth noticing, each a \
noun phrase of at most six words ("tyre tracks in the sand", "a parasail at \
the end"), `place_guess` (where this might be, at most eight words, e.g. \
"a west-coast Indian beach, Goa or Karnataka"; empty if nothing suggests a \
place) and `confidence` (low, medium or high), and `beats`: for each frame, \
its time and one short note on what it shows. Describe only what is visible; \
the person will read these as short lines on a screen, not as prose.\
"""

SHORTEN_SYSTEM = """\
You shorten one line of video dialogue so it can be spoken in less time. Keep \
its meaning, the speaker's tone and any names or numbers. Reply with the new \
line only.\
"""


READ_SYSTEM = """\
You read the transcript of a short video and introduce it to the person about \
to edit its dialogue. Return `opening`: one plain sentence, under thirty words \
(a second only when one cannot carry it), leading with the one thing worth \
knowing before deciding what to change — what is said once, what is never \
said, where the offer, brand or price lands — with times as m:ss. The screen \
already shows how many lines and speakers there are and the file's name, so \
never repeat those. For example: "The offer is never said; the brand comes up \
once, at 0:07." Return `roles`: \
for each speaker, by the name the transcript shows, the role they play in the \
clip as a short noun phrase a person would call them by — "Customer", \
"Shopkeeper", "Presenter", "Narrator", "Host", "Guest" — and `why` in one \
short sentence. Never invent a personal name.\
"""

class _Shortening(BaseModel):
    new_text: str


class _Beat(BaseModel):
    at: float
    note: str


class _Sight(BaseModel):
    opening: str
    setting: str
    mood: str
    people: str
    text_on_screen: str
    place_guess: str
    confidence: Literal["low", "medium", "high"]
    beats: list[_Beat]
    details: list[str] = Field(default_factory=list, description="Three to five things worth noticing, each a noun phrase of at most six words.")


class _Role(BaseModel):
    speaker: str = Field(description="The speaker's name exactly as the transcript shows it.")
    role: str = Field(description="A short noun phrase for who they are in the clip: Customer, Shopkeeper, Presenter…")
    why: str


class _Reading(BaseModel):
    opening: str
    roles: list[_Role]


def render_look_request(frames: Sequence[Frame], duration: float) -> list[dict]:
    """The frames as image blocks, each introduced by its time, then the ask."""
    content: list[dict] = []
    for f in frames:
        data = base64.standard_b64encode(Path(f.path).read_bytes()).decode("ascii")
        content.append({"type": "text", "text": f"Frame at {f.at:.1f} s:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": f"The clip is {duration:.1f} s long and has no speech. Describe what the picture shows."})
    return content


def to_sight(reading: _Sight) -> Sight:
    return Sight(
        opening=reading.opening.strip(), setting=reading.setting.strip(), mood=reading.mood.strip(),
        people=reading.people.strip(), text_on_screen=reading.text_on_screen.strip(),
        place_guess=reading.place_guess.strip(), confidence=reading.confidence,
        beats=tuple({"at": round(b.at, 2), "note": b.note.strip()} for b in reading.beats),
        details=tuple(d.strip() for d in reading.details if d.strip())[:5],
    )


def render_read_request(lines: Sequence[Line]) -> str:
    out = ["Transcript:"]
    for line in lines:
        who = f" {line.speaker}:" if line.speaker else ""
        out.append(f"{line.index}. [{_mmss(line.start)}]{who} {line.text}")
    return "\n".join(out)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def to_reading(reading: _Reading, lines: Sequence[Line]) -> Reading:
    names = {line.speaker for line in lines if line.speaker}
    roles = []
    seen = set()
    for r in reading.roles:
        speaker, role = r.speaker.strip(), r.role.strip().strip('"').rstrip(".")
        if speaker in names and role and speaker not in seen:
            seen.add(speaker)
            roles.append(Role(speaker, role[:1].upper() + role[1:], r.why.strip()))
    return Reading(opening=reading.opening.strip(), roles=tuple(roles))


class ClaudePlanner:
    identity = "claude"

    def __init__(
        self, api_key: str, workspace_id: str | None, *, model: str = MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self._model = model

    def _parse(self, system: str, content, output_format, effort: str, meter: Meter | None):
        try:
            response = self._client.messages.parse(
                model=self._model, max_tokens=MAX_TOKENS, output_config={"effort": effort},
                system=system, messages=[{"role": "user", "content": content}],
                output_format=output_format,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise PlannerError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise PlannerConfigError(
                f"Claude refused the request ({exc.status_code}). "
                "Check ANTHROPIC_API_KEY and ANTHROPIC_WORKSPACE_ID."
            ) from None
        if meter is not None and response.usage is not None:
            meter(self._model, response.usage.input_tokens, response.usage.output_tokens)
        return response

    def look(self, frames: Sequence[Frame], duration: float, meter: Meter | None = None) -> Sight:
        response = self._parse(LOOK_SYSTEM, render_look_request(frames, duration), _Sight, "low", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return Sight(opening=f"No one speaks. {duration:.1f} s of picture.")
        return to_sight(response.parsed_output)

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        content = (f'Line: "{text}"\nIt must be spoken in about {share:.0%} of the time it takes now'
                   f" (the original line there was \"{line.text}\").")
        response = self._parse(SHORTEN_SYSTEM, content, _Shortening, "low", meter)
        if response.parsed_output is None:
            return None
        short = response.parsed_output.new_text.strip().strip('"').strip()
        return short if short and short != text else None

    def read(self, lines: Sequence[Line], meter: Meter | None = None) -> Reading:
        response = self._parse(READ_SYSTEM, render_read_request(lines), _Reading, "low", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            n = len(lines)
            return Reading(opening=f"{n} {'line' if n == 1 else 'lines'}.")
        return to_reading(response.parsed_output, lines)
