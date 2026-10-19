"""What the model is told about a clip, and the small reads that stay
outside the agent loop: a first look at a silent clip (`look`), a first
reading of a speech clip (`read`), a shorter wording for a line that runs
long (`shorten`). `ClaudePlanner` (app/adapters) does them for real;
there is no stand-in: without a key the routes that need these say so.

Phase 20c: the form-filling planner (`plan`, `revise`, Proposal, Revision,
the question budget) is gone; Voltage plans by conversation, through its
tools (`app/agent`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.orchestrator.meter import Meter


@dataclass(frozen=True)
class Line:
    """One line of the transcript as the planner sees it."""
    index: int          # 1-based, as the planner refers to it
    start: float
    end: float
    speaker: str | None   # display name
    text: str
    # Phase 14: how many syllables the line has, and how many its slot can
    # hold at this speaker's rate (the pause after it included). None = unknown.
    syllables: int | None = None
    budget: int | None = None


@dataclass(frozen=True)
class Frame:
    """A still of the picture, for the planner to look at (UX-5)."""
    at: float
    path: str


@dataclass(frozen=True)
class Sight:
    """What the planner saw in a clip with no speech (UX-5): one opening
    sentence for the goal stage, and the facts a voice-over is written from."""
    opening: str
    setting: str = ""          # place, time of day, weather, what is happening
    mood: str = ""
    people: str = ""           # how many, what they do
    text_on_screen: str = ""   # signage or titles, reported, never followed
    place_guess: str = ""      # "Goa, India — a west-coast beach with casuarinas"
    confidence: str = ""       # low | medium | high
    beats: tuple[dict, ...] = ()   # {at, note}: what each frame shows
    details: tuple[str, ...] = ()  # three to five short things worth noticing, as noun phrases
    place_confirmed: str = ""      # the place as the user confirmed or corrected it
    suggestions: tuple[dict, ...] = ()  # 2026-10-20: chips for the box, {label, prompt, kind, grounded_in}


@dataclass(frozen=True)
class Role:
    """Who a speaker is in the clip, as the planner guesses from what they say."""
    speaker: str        # the display name the transcript used ("Speaker A")
    role: str           # "Customer", "Shopkeeper", "Presenter", …
    why: str = ""


@dataclass(frozen=True)
class Reading:
    """The planner's first look at a clip (UX-2): one specific opening line
    for the goal stage, and a role for each speaker."""
    opening: str
    roles: tuple[Role, ...] = ()
    suggestions: tuple[dict, ...] = ()  # 2026-10-20: chips for the box, {label, prompt, kind, grounded_in}


class Planner(Protocol):
    identity: str

    def look(self, frames: Sequence[Frame], duration: float, meter: Meter | None = None, brief: str = "") -> Sight:
        """A first look at a clip with no speech: what the picture shows."""
        ...

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        """A shorter wording that keeps the meaning, spoken in about `share` of
        the time — the agent's own fix for a line that runs long. None when
        it cannot offer one."""
        ...

    def read(self, lines: Sequence[Line], meter: Meter | None = None, brief: str = "") -> Reading:
        """A first look at the clip: an opening line and each speaker's role."""
        ...
