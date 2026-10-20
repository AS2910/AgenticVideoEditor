"""Who did something (F5, F7): the user, Voltage, or a reviewer, with a name to show."""
from __future__ import annotations

from dataclasses import dataclass

KINDS = ("user", "voltage", "reviewer")


@dataclass(frozen=True)
class Actor:
    kind: str           # user | voltage | reviewer
    name: str = ""      # the owner id, "Voltage", or the reviewer's name

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"an actor is one of {', '.join(KINDS)}")


VOLTAGE = Actor("voltage", "Voltage")


def user(owner: str) -> Actor:
    return Actor("user", owner)
