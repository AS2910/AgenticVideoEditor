"""G6: liveness for consent. Before a speaker's voice is cloned, the person
reads a random sentence aloud; the recording and the result are stored.

    prompt() -> str                                     a fresh sentence with a 4-digit code
    provider.verify(audio_path, sentence) -> Result     passed, why

`FakeLiveness` (test mode) passes any readable recording of at least one
second and fails an empty or unreadable one with a sentence; it does not
check the words or the face. A real provider (speech match against the
sentence, a voice match against the video's speaker, anti-replay) goes
behind the same `verify` (SETUP_NEEDED.md).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

SENTENCES = (
    "I am recording this today, and I agree to let Voltage use my voice for this video.",
    "This is my own voice, and I am happy for Voltage to make new lines with it.",
    "I am reading this aloud now to say yes to Voltage using my voice.",
    "My voice can be used for the lines in this video. I am saying so out loud.",
)
MIN_SECONDS = 1.0


@dataclass(frozen=True)
class LivenessResult:
    passed: bool
    reason: str
    provider: str
    test_mode: bool


class LivenessProvider(Protocol):
    name: str
    test_mode: bool

    def verify(self, audio_path: Path, sentence: str) -> LivenessResult: ...


def prompt(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    code = " ".join(str(rng.randint(0, 9)) for _ in range(4))
    return f"{rng.choice(SENTENCES)} My code is {code}."


class FakeLiveness:
    name = "fake"
    test_mode = True

    def __init__(self, seconds_of: Callable[[Path], float]) -> None:
        self.seconds_of = seconds_of

    def verify(self, audio_path: Path, sentence: str) -> LivenessResult:
        try:
            seconds = float(self.seconds_of(audio_path))
        except Exception:  # noqa: BLE001 - a file we cannot read is a failed attempt, said plainly
            return LivenessResult(False, "That recording could not be read. Record the sentence again.", self.name, True)
        if seconds < MIN_SECONDS:
            return LivenessResult(False, "That recording is too short. Read the whole sentence aloud.", self.name, True)
        return LivenessResult(True, "Passed in test mode: the recording was kept, the words were not checked.", self.name, True)
