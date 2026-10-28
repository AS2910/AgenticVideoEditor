"""The fast path for small edits (run 5 item 6).

A line changed in the transcript and sent with Enter is a direct instruction:
the words are known, the line is known, the voice and delivery are the line's
own. A full turn would still spend a planning call or two on it. The router
sends such an edit straight to one take instead:

- fast: one existing line, at most MAX_WORDS words changed, no new line, the
  voice as the line has it. One take is voiced with the line's current voice
  and delivery through the same `synthesize_take` the agent uses (its
  pre-flight, fit ladder, word rules, job and spend gates), and stands as a
  proposal ready to hear. No Claude call.
- full: everything else, as before (the sentence the editor would have said
  goes to Voltage as a turn).

When the quick take does not fit its gap, or the spend would need a yes, the
fast path hands over to the full turn with a note; the item and the paid take
stay where the full turn finds them.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.agent.guards import TurnStopped, WaitingForUser
from app.jobs.pause import step_name

STOPPED = "Stopped by you."

MAX_WORDS = 8
_WORD = re.compile(r"\S+")


def _words(text: str) -> list[str]:
    return [w.strip(".,!?;:\"“”‘’()").lower() for w in _WORD.findall(text or "")]


def changed_words(before: str, after: str) -> int:
    """How many words the edit changes: for each changed run, the longer of
    what went and what came ("20%" -> "30%" is 1; three words for two is 3)."""
    a, b = _words(before), _words(after)
    out = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            out += max(i2 - i1, j2 - j1)
    return out


@dataclass(frozen=True)
class Route:
    fast: bool
    reason: str          # why, in a few plain words (logged, and shown when it goes the full way)
    changed: int = 0


def route(before: str, after: str, *, on_line: bool, new_line: bool, voice_changed: bool,
          busy: bool = False, over_limit: bool = False, question_open: bool = False) -> Route:
    """Fast or full, cheapest test first. `on_line`: the edit names one
    existing spoken line (or the proposal on it)."""
    n = changed_words(before, after)
    if new_line or not on_line:
        return Route(False, "a new line", n)
    if voice_changed:
        return Route(False, "a different voice", n)
    if n == 0:
        return Route(False, "no words changed", n)
    if n > MAX_WORDS:
        return Route(False, f"{n} words changed", n)
    if question_open:
        return Route(False, "Voltage's question is still open", n)
    if over_limit:
        return Route(False, "over your spending limit", n)
    if busy:
        return Route(False, "Voltage is busy", n)
    return Route(True, f"{n} {'word' if n == 1 else 'words'} changed", n)


@dataclass(frozen=True)
class Outcome:
    made: bool                      # a take stands on the line, ready to hear
    item_id: str | None = None
    candidate_id: str | None = None
    cost_usd: float = 0.0
    step: str | None = None         # the step line the thread shows
    note: str | None = None         # why it goes the full way instead (when not made)
    fallback: bool = False          # not made, and the full turn should take it (fit, a yes); a vendor failure stays failed


_ESTIMATE = re.compile(r"about (\d+(?:\.\d+)?) s for (\d+(?:\.\d+)?) s")


def _fit_note(item, step: str | None = None) -> str:
    failure = getattr(item, "fit_failure", None) if item is not None else None
    needs, has = (failure or {}).get("needs"), (failure or {}).get("has")
    if not (needs and has) and (m := _ESTIMATE.search(step or "")):
        needs, has = float(m.group(1)), float(m.group(2))
    if needs and has:
        return f"The new words run long for the gap ({needs:.1f} s for {has:.1f} s), so Voltage is taking it from here."
    return "The quick take did not fit, so Voltage is taking it from here."


def voice(wb, turn, *, line_no: int | None, item_id: str | None, text: str, voice_id: str,
          direction: str | None) -> Outcome:
    """One take on the line, through the agent's own tool. Never raises for a
    take that could not be made: the outcome says to go the full way."""
    from app.agent.tools import _synthesize_take
    args = {"text": text, "voice_id": voice_id, "direction": direction or "", "line": line_no, "item_id": item_id or "",
            "fit": "fit", "picture": "default", "model": "default", "mix": "replace"}
    taken = len(turn.takes)
    # Addendum 3.5: pause point before the take (nothing has run yet); Stop while paused ends it unvoiced.
    turn.pause_point(step_name(None))
    if turn.stop_requested():
        return Outcome(False, note=STOPPED)
    try:
        result = _synthesize_take(wb, turn, args)
    except WaitingForUser as asked:
        cost = f" (about ${asked.cost_usd:.2f})" if asked.cost_usd else ""
        return Outcome(False, note=f"This take needs your go-ahead{cost}, so Voltage is asking.", fallback=True)
    except TurnStopped as stopped:
        return Outcome(False, note=str(stopped))
    # Pause point after the take: it is paid for and kept; what follows (the story checks) waits for Resume.
    turn.pause_point(step_name("synthesize_take", {"line": line_no}))
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    if len(turn.takes) > taken:
        made = turn.takes[-1]
        item = next((i for i in (plan.items if plan else ()) if i.candidate_id == made), None)
        return Outcome(True, item.item_id if item else item_id, made, result.cost_usd, result.step)
    item = None
    if plan is not None:
        item = plan.item(item_id) if item_id else next(
            (i for i in reversed(plan.items) if i.kind == "planned" and i.new_text == text), None)
    if (item is not None and getattr(item, "fit_failure", None)) or "too long" in (result.step or "").lower():
        return Outcome(False, item.item_id if item else None, cost_usd=result.cost_usd, step=result.step,
                       note=_fit_note(item, result.step), fallback=True)
    if item is None:
        # Refused before anything was voiced (a voice the catalogue does not know, a cap): Voltage can sort it out.
        return Outcome(False, cost_usd=result.cost_usd, step=result.step, fallback=True,
                       note="That one needs Voltage, so it is taking it from here.")
    # The vendor failed: the row says why; a full turn would only fail again.
    return Outcome(False, item.item_id if item else None, cost_usd=result.cost_usd, step=result.step,
                   note=getattr(item, "error", None) if item is not None else None)


def lines_now(lines, edits, items) -> list:
    """Every spoken line as the video will read once the proposals go in: the
    words of a live replacement on it, else of a proposal waiting on it, else as
    shot. For the story checks."""
    from app.agent.story_checks import StoryLine

    def on(sel, ln) -> bool:
        return abs(sel.start - ln.start) < 0.01 and abs(sel.end - ln.end) < 0.01
    out = []
    for ln in lines:
        text = ln.text
        for e in edits:
            if e.plan.mix == "replace" and on(e.plan.selection, ln):
                text = e.plan.new_text
        for i in items:
            if i.kind == "planned" and i.mix == "replace" and i.status in ("ready", "working", "planned") and on(i.selection, ln):
                text = i.new_text
        out.append(StoryLine(ln.start, text))
    return out


def line_voice(take_voice: str | None, speaker) -> tuple[str, set[str]]:
    """The voice the line speaks in now, as the editor opens on it (the take on
    it, else the speaker's chosen voice, else their own: ""), and the ids that
    all mean "the speaker's own voice" (voiced as "" so their clone is used)."""
    own = {v for v in (getattr(speaker, "voice_id", None), getattr(speaker, "clone_voice_id", None)) if v}
    return (take_voice or getattr(speaker, "voice_id", None) or ""), own
