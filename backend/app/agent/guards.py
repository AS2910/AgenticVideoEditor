"""What Voltage may do on its own (Phase 20).

Three classes of tool, by what they cost the user:
- **free**: looking and listening; nothing is spent or changed.
- **spend**: money leaves (a take, a designed voice); bounded by the project's
  ceiling and a per-turn cap, and under "Check with me" asked once per turn
  only past the user's limit (Run 5 item 2: "Ask me before spending more
  than $X", $0.25 to start); under it, paid steps just run.
- **commit**: what the user has changes (ship, render); under "Check with me"
  always asked; under "Just do it" done, except deleting, which always asks.

Nothing here is about taste. The guards are money, reversibility, consent
and scope; which voice, tone or wording to prefer is the model's call.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Guard(str, Enum):
    FREE = "free"
    SPEND = "spend"
    COMMIT = "commit"


class WaitingForUser(Exception):
    """A tool needs the user before it runs. The turn ends with this question;
    the user's answer is the next turn, and the agent carries on from there."""

    def __init__(self, question: str, options: tuple[str, ...] = ("Go ahead", "Not yet"),
                 guess: str | None = "Go ahead", *, gate: bool = True, cost_usd: float | None = None,
                 details: tuple[str | None, ...] | None = None) -> None:
        super().__init__(question)
        self.question = question
        self.options = options
        # A quieter line under each option's short label (the full sentence); None where there is none.
        self.details = tuple(details) if details and any(details) else None
        self.guess = guess if guess in options else options[0]
        # A gate question (a paid or committing step waits); its first option is the yes.
        self.gate = gate
        # What the waiting step would spend, so the card can show it beside
        # what the turn has left; None when the step is free.
        self.cost_usd = cost_usd


class TurnStopped(Exception):
    """A cap of the turn was reached; the agent is told, and the turn ends."""


# Spoken in the composer, approves the paid or committing step Voltage asked about.
GO_WORDS = ("go", "go ahead", "ok", "okay", "yes", "sure", "fine", "yep", "do it", "yes please")


def is_go(text: str) -> bool:
    return text.strip().rstrip(".!").lower() in GO_WORDS


@dataclass
class TurnBudget:
    """The caps of one turn: money, tool calls and wall clock."""
    usd: float = 0.50
    calls: int = 25
    seconds: float = 600.0
    started: float = field(default_factory=time.monotonic)
    calls_made: int = 0
    # The paid step the cap last refused: what it would have cost (0: none
    # refused), so the question that follows can offer exactly what it needs.
    refused_usd: float = 0.0
    # What `refuses` leaves out of the spent figure: on a turn carried on after
    # "allow $x more", that continuation's own thinking, so the raise covers
    # the step it was for (the thinking still shows in the trace).
    excused: Callable[[], float] | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def take_call(self) -> None:
        """One more tool call. Raises when the turn has had its share."""
        self.calls_made += 1
        if self.calls_made > self.calls:
            raise TurnStopped(f"This turn has used its {self.calls} steps. Say what to do next and I'll carry on.")
        if self.elapsed() > self.seconds:
            raise TurnStopped(f"This turn has run for {self.seconds / 60:.0f} minutes. Say what to do next and I'll carry on.")

    def refuses(self, spent_usd: float, next_usd: float) -> str | None:
        """Why a paid step may not run now, in a sentence; None when it may."""
        if self.excused is not None:
            spent_usd = max(0.0, spent_usd - self.excused())
        if spent_usd + next_usd > self.usd + 1e-9:
            self.refused_usd = next_usd
            return (f"This step would cost about ${next_usd:.2f}; the turn's cap is ${self.usd:.2f} and "
                    f"${spent_usd:.2f} is spent. Ask the user whether to go on, or do it next turn; "
                    "their card offers to allow exactly what this step needs, so leave that option out of yours.")
        return None

    def needed_usd(self, spent_usd: float) -> float:
        """What the cap must rise by, to the cent upwards, for the step it last
        refused to run after `spent_usd`; 0 when nothing was refused or it fits."""
        if self.refused_usd <= 0:
            return 0.0
        if self.excused is not None:
            spent_usd = max(0.0, spent_usd - self.excused())
        short = spent_usd + self.refused_usd - self.usd
        return math.ceil(round(short * 100, 6)) / 100 if short > 1e-9 else 0.0
