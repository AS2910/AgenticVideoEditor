"""The six scenarios: what the user says, on which clip, and what counts as
doing only what was asked.

`targets` names the original lines (by index into the clip's transcript
statements) the turn is asked to change; `adds` is how many new lines it is
asked to add. A question turn asks for neither. `expect_words` is the line as
it should read afterwards, where the user said it exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    name: str
    clip: str
    say: str
    targets: tuple = ()                    # line indexes, or ("all",)
    adds: int = 0
    expect_words: tuple[str, ...] = ()     # per target or added line, when fixed by the user
    language: str | None = None            # Whisper's hint for the takes
    question: bool = False
    notes: str = field(default="")


def _hindi_goal() -> str:
    # The words `_translate_goal` (app/api/main.py) gives a language version's
    # batch turn, for Hindi with the same voices; the runner fills {lines}
    # from the clip's own transcript, as the batch does.
    return ("Make this the Hindi version of chai.mp4: translate every line into Hindi and voice each one in place "
            "of the line it replaces, fitting that line's time. When a line runs long, let the fit ladder work first, "
            "then write it shorter in Hindi. Speak each line in the same speaker's own voice (their cloned voice when "
            "they have one, else the voice the line is in now) with model v2, the multilingual model, so it is their "
            "voice speaking Hindi.\nThe lines, as the master says them now:\n{lines}")


SCENARIOS = (
    Scenario("one_line_fix", "ad.mp4", "Make it 30% off", targets=(0,),
             expect_words=("Get 30% off today only",)),
    Scenario("five_line_rewrite", "chai.mp4",
             "Rewrite all five lines as a Diwali offer: chai and sweets at 20% off. Same speakers, same length, "
             "each line replacing the one it rewrites.", targets=("all",)),
    Scenario("new_voiceover", "silent.mp4",
             "Add a calm woman's voice-over that says “Fresh chai, every morning, right here.”", adds=1,
             expect_words=("Fresh chai, every morning, right here.",)),
    Scenario("hinglish_line", "ad.mp4", "Replace the line with “Aaj hi lo, 30% off, sirf aaj!”", targets=(0,),
             expect_words=("Aaj hi lo, 30% off, sirf aaj!",)),
    Scenario("hindi_version", "chai.mp4", _hindi_goal(), targets=("all",), language="hi"),
    Scenario("question", "ad.mp4", "How do I make a vertical version of this for Instagram Reels?", question=True),
)

BY_NAME = {s.name: s for s in SCENARIOS}
