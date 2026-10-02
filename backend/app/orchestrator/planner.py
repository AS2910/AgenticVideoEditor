"""Planning edits across the whole video from a goal (Phase 13).

A planner reads the goal with every line of the transcript and returns the
changes that carry it out, plus any it would suggest. `ClaudePlanner`
(app/adapters) does this for real; `RulePlanner` is the offline fallback — it
understands `change "X" to "Y"` across lines and nothing more — used without a
key, under AVE_DRY_RUN, and in tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.orchestrator.intent import Meter


@dataclass(frozen=True)
class Line:
    """One line of the transcript as the planner sees it."""
    index: int          # 1-based, as the planner refers to it
    start: float
    end: float
    speaker: str | None   # display name
    text: str


@dataclass(frozen=True)
class Change:
    line: int           # Line.index
    new_text: str
    mix: str = "replace"   # "replace" | "concatenate"
    reason: str = ""


@dataclass(frozen=True)
class Proposal:
    summary: str
    edits: tuple[Change, ...]
    suggestions: tuple[Change, ...] = ()


class Planner(Protocol):
    identity: str

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None) -> Proposal: ...

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        """A shorter wording that keeps the meaning, spoken in about `share` of
        the time — the agent's own fix for a line that runs long. None when
        it cannot offer one."""
        ...


_CHANGE = re.compile(
    r'(?:change|replace|say|make it)\s+"([^"]+)"\s+(?:to|with|as|into)\s+"([^"]+)"', re.IGNORECASE,
)


class RulePlanner:
    """No model: `change "X" to "Y"` is applied to every line that says X."""

    identity = "rules"

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None) -> Proposal:
        pairs = _CHANGE.findall(goal)
        if not pairs:
            return Proposal(
                summary=('Planning from a goal in your own words needs Claude. Offline, say what '
                         'to change like: change "20% off" to "30% off".'),
                edits=(),
            )
        edits = []
        for line in lines:
            text = line.text
            for old, new in pairs:
                text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
            if text != line.text:
                edits.append(Change(line.index, text, "replace", f'Says "{pairs[0][0]}"'))
        n = len(edits)
        summary = (f"Found {n} {'line' if n == 1 else 'lines'} to change." if n
                   else f'No line says "{pairs[0][0]}".')
        return Proposal(summary=summary, edits=tuple(edits))

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        return None
