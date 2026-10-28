"""Addendum 3.5 (2026-10-28): Pause, beside Stop.

Pause lets the step running now finish (the vendor call already on its way is
paid for, so it is kept), then holds at the next pause point: nothing new
starts, the video's lock stays held (handed to `pause:<turn id>`) and Up next
waits. Resume carries on from the next step, so nothing is done twice; Stop
ends it the way Stop always does. A pause nobody ends stops itself after
AUTO_STOP_S, so the lock never sticks: the deadline is in the video's settings
and on the lock row (its lease), so a restart keeps it.

The pause points (where `Pauses.hold` may wait):
  the agent loop    before every Claude request, and before every tool call
  the fast path     before its one take, and after it (before the story checks)
  a batch           before each video's turn starts; each running video's
                    turn pauses at its own points

    ask(turn_id)          Pause pressed: hold at the next pause point
    begin / hold / end    at a pause point: holding from `begin`, waiting in `hold` until resumed,
                          stopped or past the deadline, let go at `end`
    resume(turn_id)       Resume pressed
    holding(turn_id)      whether this process has the turn waiting (a restart does not)
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from app.jobs.locks import PAUSE  # noqa: F401 - the holder prefix, named once (locks.py)

AUTO_STOP_S = 30 * 60.0
# The lock's lease runs this long past the deadline, so the auto-stop (which puts the
# edit set back) ends a pause, never the lease sweep (which only deletes the row).
LEASE_GRACE_S = 6 * 3600.0

# One state per video (addendum 3, items 4 and 5), the names every surface reads;
# the front end's are in `frontend/src/lib/videoState.ts`.
VIDEO_STATES = ("ready", "working", "paused")

# The words, exactly as the owner wrote them (BRIEF2, addendum 3, item 5).
SPENT_SO_FAR = "Spent so far: ${:.2f}"
PAUSED_WORDS = "Paused. ${:.2f} spent so far is still charged. Resume to finish."
STOPPED_WORDS = "Stopped. Nothing in your video changed. ${:.2f} spent is still charged."
# Stop could not take everything back (something outside the edit set the turn
# changed, such as the mix): the video did change, so the words say so and what to do.
STOPPED_LANDED_WORDS = ("Stopped. Part of this change was already in your video: "
                        "use Undo on this turn to take it out. ${:.2f} spent is still charged.")

# "Paused after <step>": what the step that finished was, in the strip's words.
STEP_NAMES = {
    None: "starting", "thinking": "planning", "synthesize_take": "voicing a line", "design_voice": "designing a voice",
    "clone_speaker": "cloning a voice", "ship": "putting lines in the video", "save_voice": "keeping a voice",
    "add_voice_from_library": "adding a voice", "hear": "listening", "look_at_frames": "looking at the picture",
    "read_transcript": "reading the lines", "measure": "checking a take", "find_room": "finding room for a line",
    "plan_lines": "planning the lines", "list_voices": "looking through the voices", "remove_line": "taking a line out",
    "shift_line": "moving a line", "move_item": "moving a take", "set_role": "setting a line's role",
    "undo_edit": "undoing an edit", "keep_take": "keeping a take", "drop_item": "dropping a line",
}


def step_name(tool: str | None, args: dict | None = None) -> str:
    """The step that just finished, as "Paused after ..." ends: "voicing line 2", "planning"."""
    line = (args or {}).get("line")
    if tool == "synthesize_take" and isinstance(line, int) and not isinstance(line, bool):
        return f"voicing line {line}"
    return STEP_NAMES.get(tool, "the last step")


class Pauses:
    """Which turns were asked to pause, and the hold at a pause point. In this
    process only: what survives a restart is the lock row and the settings."""

    def __init__(self, clock: Callable[[], float] = time.time, tick: float = 0.2) -> None:
        self.clock = clock
        self.tick = tick
        self._cv = threading.Condition()
        self._asked: set[str] = set()
        self._holding: set[str] = set()

    def ask(self, turn_id: str) -> None:
        with self._cv:
            self._asked.add(turn_id)
            self._cv.notify_all()

    def asked(self, turn_id: str) -> bool:
        with self._cv:
            return turn_id in self._asked

    def holding(self, turn_id: str) -> bool:
        with self._cv:
            return turn_id in self._holding

    def resume(self, turn_id: str) -> bool:
        """Resume: the hold lets go (or a pause not reached yet is called off). True when one was asked."""
        with self._cv:
            was = turn_id in self._asked
            self._asked.discard(turn_id)
            self._cv.notify_all()
        return was

    def wake(self) -> None:
        """Stop pressed: every hold looks again (the one stopped lets go)."""
        with self._cv:
            self._cv.notify_all()

    def forget(self, turn_id: str) -> None:
        with self._cv:
            self._asked.discard(turn_id)
            self._cv.notify_all()

    def begin(self, turn_id: str) -> None:
        """The turn is about to hold: from here on Resume and Stop reach it in this process
        (before its lock even reads paused), never the restart path."""
        with self._cv:
            self._holding.add(turn_id)

    def end(self, turn_id: str) -> None:
        with self._cv:
            self._holding.discard(turn_id)
            self._asked.discard(turn_id)
            self._cv.notify_all()

    def hold(self, turn_id: str, until: float, stopped: Callable[[], bool]) -> str:
        """Wait at a pause point (between `begin` and `end`): "resumed", "stopped", or
        "expired" (the deadline passed). It looks every `tick`, so a test's clock moved
        forward is seen at once."""
        with self._cv:
            while True:
                if stopped():
                    return "stopped"
                if turn_id not in self._asked:
                    return "resumed"
                if self.clock() >= until:
                    return "expired"
                self._cv.wait(self.tick)
