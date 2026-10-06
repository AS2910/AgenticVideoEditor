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
    # Phase 14: how many syllables the line has, and how many its slot can
    # hold at this speaker's rate (the pause after it included). None = unknown.
    syllables: int | None = None
    budget: int | None = None


@dataclass(frozen=True)
class Change:
    line: int           # Line.index; 0 for a line placed by time on a silent clip (UX-5)
    new_text: str
    mix: str = "replace"   # "replace" | "concatenate" | "over" | "layer" (placed, over the sound there)
    reason: str = ""
    # Who says it, by the name the transcript uses — for an added line that
    # another person speaks. None = the line's own speaker.
    speaker: str | None = None
    # UX-5: a change placed at a time rather than on a line — the span it covers.
    start: float | None = None
    end: float | None = None

    @property
    def placed(self) -> bool:
        return self.start is not None and self.end is not None


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


@dataclass(frozen=True)
class Question:
    """One thing the planner needs to know before it can plan well — with
    its own guess, so the user can just say go."""
    text: str
    options: tuple[str, ...]
    guess: str | None = None


@dataclass(frozen=True)
class Proposal:
    summary: str
    edits: tuple[Change, ...]
    suggestions: tuple[Change, ...] = ()
    # What the planner noticed while reading, in the order it noticed it.
    findings: tuple[str, ...] = ()
    question: Question | None = None


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


@dataclass(frozen=True)
class ItemView:
    """One item of an existing plan, as the planner sees it when revising."""
    item_id: str
    line: int                # Line.index of the line it is on
    old_text: str
    new_text: str
    mix: str
    delivery: str | None
    enabled: bool
    status: str              # "planned" | "ready" | …
    speaker: str | None = None


@dataclass(frozen=True)
class ItemChange:
    """What to change about one item; None leaves that field alone."""
    item_id: str
    enabled: bool | None = None
    new_text: str | None = None
    mix: str | None = None
    delivery: str | None = None
    # Delivery is tri-state: `clear_delivery` sets it back to "as spoken".
    clear_delivery: bool = False


@dataclass(frozen=True)
class Revision:
    """A change to a plan in the user's words (UX-2): edits to its items and
    new items, applied in place so the takes already voiced survive. When the
    instruction is a new goal altogether, `new_goal` is set and nothing else."""
    summary: str
    changes: tuple[ItemChange, ...] = ()
    additions: tuple[Change, ...] = ()
    new_goal: bool = False


class Planner(Protocol):
    identity: str

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None, answer: tuple[str, str] | None = None,
             sight: Sight | None = None, duration: float | None = None,
             answers: Sequence[tuple[str, str]] = ()) -> Proposal:
        """`answer` is (the question asked earlier, what the user said). On a
        clip with no lines, `sight` and `duration` stand in for the transcript
        and `answers` carries every question and answer of the brief so far."""
        ...

    def look(self, frames: Sequence[Frame], duration: float, meter: Meter | None = None) -> Sight:
        """A first look at a clip with no speech: what the picture shows."""
        ...

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        """A shorter wording that keeps the meaning, spoken in about `share` of
        the time — the agent's own fix for a line that runs long. None when
        it cannot offer one."""
        ...

    def read(self, lines: Sequence[Line], meter: Meter | None = None) -> Reading:
        """A first look at the clip: an opening line and each speaker's role."""
        ...

    def revise(self, instruction: str, items: Sequence[ItemView], lines: Sequence[Line],
               goal: str, meter: Meter | None = None) -> Revision:
        """Change an existing plan as the instruction says."""
        ...


_CHANGE = re.compile(
    r'(?:change|replace|say|make it)\s+"([^"]+)"\s+(?:to|with|as|into)\s+"([^"]+)"', re.IGNORECASE,
)
_QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
# A narration pace, syllables per second, for a line placed over a silent clip.
NARRATION_RATE = 4.0
# How many questions the brief may ask before it must plan (UX-5, SV-3).
MAX_QUESTIONS = 3


class RulePlanner:
    """No model: `change "X" to "Y"` is applied to every line that says X."""

    identity = "rules"

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None, answer: tuple[str, str] | None = None,
             sight: Sight | None = None, duration: float | None = None,
             answers: Sequence[tuple[str, str]] = ()) -> Proposal:
        if not lines and duration:
            return self._plan_voiceover(goal, duration)
        speakers = {line.speaker for line in lines if line.speaker}
        findings = (f"{len(lines)} {'line' if len(lines) == 1 else 'lines'}"
                    + (f", {len(speakers)} speakers" if len(speakers) > 1 else ""),)
        pairs = _CHANGE.findall(goal)
        if not pairs:
            return Proposal(
                summary=('Planning from a goal in your own words needs Claude. Offline, say what '
                         'to change like: change "20% off" to "30% off".'),
                edits=(), findings=findings,
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
        said = sum(1 for line in lines if re.search(re.escape(pairs[0][0]), line.text, re.IGNORECASE))
        findings += (f'"{pairs[0][0]}" is said {said} {"time" if said == 1 else "times"}.',)
        return Proposal(summary=summary, edits=tuple(edits), findings=findings)

    def _plan_voiceover(self, goal: str, duration: float) -> Proposal:
        """Offline, on a silent clip: words in quotes are placed from half a
        second in, over the picture, for as long as they take to say."""
        from app.media.fit import syllables
        quoted = [a or b for a, b in _QUOTED.findall(goal)]
        if not quoted:
            return Proposal(
                summary=('No one speaks in this clip. Offline I need the words in quotes, like: '
                         'say "Welcome to Goa". With Claude on, ask me to look at the clip and help.'),
                edits=(), findings=(f"{duration:.1f} s of picture, no speech.",),
            )
        text = quoted[0].strip()
        start = min(0.5, max(0.0, duration - 0.5))
        needs = max(0.8, syllables(text) / NARRATION_RATE + 0.3)
        end = round(min(duration, start + needs), 2)
        return Proposal(
            summary=f"One line, placed over the picture from {start:.1f} s.",
            edits=(Change(0, text, "layer", "Placed at the start, over the picture", start=start, end=end),),
            findings=(f"{duration:.1f} s of picture, no speech.",),
        )

    def look(self, frames: Sequence[Frame], duration: float, meter: Meter | None = None) -> Sight:
        n = len(frames)
        return Sight(opening=f"No one speaks. {duration:.1f} s of picture, {n} {'frame' if n == 1 else 'frames'}.")

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        return None

    def read(self, lines: Sequence[Line], meter: Meter | None = None) -> Reading:
        speakers = {line.speaker for line in lines if line.speaker}
        n = len(lines)
        who = (f"{len(speakers)} people speak" if len(speakers) > 1 else "one person speaks") if speakers else ""
        opening = f"{n} {'line' if n == 1 else 'lines'}" + (f", {who}." if who else ".")
        return Reading(opening=opening)

    def revise(self, instruction: str, items: Sequence[ItemView], lines: Sequence[Line],
               goal: str, meter: Meter | None = None) -> Revision:
        """Offline: "not the second one" / "skip the one at 0:17" leaves an item
        out; "put the first one back" puts it back; `change "X" to "Y"` rewords
        the items that say X. Anything else needs Claude."""
        changes: list[ItemChange] = []
        text = instruction.strip()
        back = re.search(r"\b(back|again|include)\b", text, re.IGNORECASE) is not None
        for item in _named_items(text, items, lines):
            changes.append(ItemChange(item.item_id, enabled=back))
        pairs = _CHANGE.findall(text)
        for item in items:
            new = item.new_text
            for old, repl in pairs:
                new = re.sub(re.escape(old), repl, new, flags=re.IGNORECASE)
            if new != item.new_text:
                changes.append(ItemChange(item.item_id, new_text=new))
        if not changes:
            return Revision(summary=("I couldn't follow that offline. Say which one: \"not the second one\", "
                                     "\"skip the one at 0:17\", or change \"X\" to \"Y\"."))
        n = len(changes)
        return Revision(summary=f"Changed {n} {'item' if n == 1 else 'items'} in the plan.", changes=tuple(changes))


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1}
_AT = re.compile(r"\bat\s+(\d+):(\d{2})\b")
_NTH = re.compile(r"\b(first|second|third|fourth|fifth|last|\d+)(?:st|nd|rd|th)?\b", re.IGNORECASE)


def _named_items(text: str, items: Sequence[ItemView], lines: Sequence[Line]) -> list[ItemView]:
    """The items an instruction points at: by ordinal ("the second one") or by
    the time of their line ("at 0:17")."""
    out: list[ItemView] = []
    if not re.search(r"\b(not|skip|drop|leave|without|remove|back|again|include|only)\b", text, re.IGNORECASE):
        return out
    for m in _AT.finditer(text):
        t = int(m.group(1)) * 60 + int(m.group(2))
        for item in items:
            line = next((ln for ln in lines if ln.index == item.line), None)
            if line is not None and int(line.start) == t and item not in out:
                out.append(item)
    for m in _NTH.finditer(_AT.sub("", text)):
        word = m.group(1).lower()
        n = _ORDINALS.get(word) or (int(word) if word.isdigit() else None)
        if n is None:
            continue
        idx = len(items) - 1 if n == -1 else n - 1
        if 0 <= idx < len(items) and items[idx] not in out:
            out.append(items[idx])
    return out
