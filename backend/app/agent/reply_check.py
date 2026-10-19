"""Voltage's closing words, checked against the record (p60, 2026-10-19).

At the end of a turn the reply is read for what it says about the plan's
lines — a line voiced and waiting, a line in the video — and each claim is
compared with the items as stored. A claim the record does not support gets a
"Correction: …" sentence appended, so the transcript, the header and the reply
never disagree. Deliberately plain: it reads line numbers, quoted words and a
few verbs, and only flags what it can tie to an item.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

READY_WORDS = re.compile(r"\b(ready|waiting|voiced|redone|re-?voiced|to hear|can hear|hear it|play (?:it|them|both)|you can play)\b", re.I)
IN_VIDEO_WORDS = re.compile(r"\b(in the video|added (?:it|them|both)|shipped|is now in|are now in)\b", re.I)
NOT_WORDS = re.compile(r"\b(not|couldn't|could not|didn't|did not|failed|haven't|have not|no take)\b", re.I)
ALL_WORDS = re.compile(r"\b(both lines|both of them|all (?:the |\d+ |two |three |four )?lines|every line)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _line_of(item: Any, lines: Sequence[Any]) -> int | None:
    for ln in lines:
        if abs(ln.start - item.selection.start) < 0.01 and abs(ln.end - item.selection.end) < 0.01:
            return ln.index
    return None


def _mentions(sentence: str, item: Any, line_no: int | None) -> bool:
    if line_no is not None and re.search(rf"\bline {line_no}\b", sentence, re.I):
        return True
    words = " ".join((item.new_text or "").split()[:4]).strip(" .,!?\"“”")
    return bool(words) and len(words) >= 8 and words.lower() in sentence.lower()


def corrections(reply: str, items: Sequence[Any], lines: Sequence[Any]) -> list[str]:
    """The corrections the reply needs, one sentence each (empty when it matches the record)."""
    if not reply:
        return []
    live = [i for i in items if getattr(i, "kind", "planned") == "planned" and i.status != "dismissed"]
    out: list[str] = []
    sentences = SENTENCE.split(reply)
    for item in live:
        n = _line_of(item, lines)
        said_ready = said_in = False
        for s in sentences:
            about = _mentions(s, item, n) or (ALL_WORDS.search(s) is not None and item.old_text)
            if not about:
                continue
            negated = NOT_WORDS.search(s) is not None
            if READY_WORDS.search(s) and not negated:
                said_ready = True
            if IN_VIDEO_WORDS.search(s) and not negated:
                said_in = True
        name = f"line {n}" if n is not None else f"the line “{(item.new_text or '')[:40]}”"
        if said_in and item.status != "approved":
            state = "proposed and waiting for your Add it" if item.status == "ready" else _plain(item)
            out.append(f"Correction: {name} is not in the video yet; it is {state}.")
        elif said_ready and item.status not in ("ready", "approved"):
            out.append(f"Correction: {name} is {_plain(item)}.")
    return out


def _plain(item: Any) -> str:
    if item.status == "failed":
        why = (item.error or "").rstrip(".")
        return f"not voiced: {why}" if why else "not voiced"
    if item.status == "needs-you":
        return "waiting on a question for you"
    if item.status in ("planned", "working"):
        return "not voiced yet"
    return item.status
