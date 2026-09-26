"""Reading what the user asked for (Phase 8).

An interpreter turns the chat message, the conversation so far and what is
under the selection into an Intent. `ClaudeInterpreter` (app/adapters) reads
free-form requests; `RuleInterpreter` is the offline fallback — the old
`change "X" to "Y"` rule — used without a key, under AVE_DRY_RUN, and in tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.domain.models import Intent, Selection, Transcript

# Words either side of the selection shown to the interpreter.
CONTEXT_WORDS = 12


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str


@dataclass(frozen=True)
class EditContext:
    """What the interpreter knows about where the edit goes."""
    selection: Selection
    duration: float
    selected: str   # the words inside the selection, "" when none
    before: str     # words leading up to it
    after: str      # words following it

    @property
    def has_speech(self) -> bool:
        return self.selected != ""


def edit_context(transcript: Transcript, selection: Selection, duration: float) -> EditContext:
    words = transcript.words
    inside = [w.text for w in words if w.end > selection.start and w.start < selection.end]
    before = [w.text for w in words if w.end <= selection.start][-CONTEXT_WORDS:]
    after = [w.text for w in words if w.start >= selection.end][:CONTEXT_WORDS]
    return EditContext(selection, duration, " ".join(inside), " ".join(before), " ".join(after))


class Interpreter(Protocol):
    def interpret(self, prompt: str, history: Sequence[Turn], context: EditContext) -> Intent: ...


# The quoted text after "to", or failing that the last quoted text.
_TO_QUOTED = re.compile(r'to\s+"([^"]+)"\s*$', re.IGNORECASE)
_QUOTED = re.compile(r'"([^"]+)"')


class RuleInterpreter:
    """No model: the line to speak is the quoted text, or the whole message."""

    identity = "rules"

    def interpret(self, prompt: str, history: Sequence[Turn], context: EditContext) -> Intent:
        prompt = prompt.strip()
        match = _TO_QUOTED.search(prompt)
        if match:
            return Intent(action="speak", new_text=match.group(1))
        quoted = _QUOTED.findall(prompt)
        return Intent(action="speak", new_text=quoted[-1] if quoted else prompt)
