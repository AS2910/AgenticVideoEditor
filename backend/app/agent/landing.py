"""Where a line's key word lands against its beat (2026-10-20).

A line written for a moment ("Blue goes DOWN!" for the knockdown at 0:13)
works only if its key word is heard within 300 ms of it. The take's own word
times, offset by where it plays, tell exactly when the word lands.
"""
from __future__ import annotations

import re

WITHIN = 0.3


def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def lands_at(words, starts_at: float, key_word: str) -> float | None:
    """When `key_word` (its first word, if several) is heard: the take's start plus the word's own time."""
    key = _norm((key_word or "").split()[0]) if key_word and key_word.split() else ""
    if not key:
        return None
    for w in words or ():
        if _norm(w.text) == key or (len(key) > 3 and _norm(w.text).startswith(key)):
            return round(starts_at + w.start, 3)
    return None


def landing_note(words, starts_at: float, key_word: str, beat_at: float) -> tuple[str, float | None]:
    """A sentence for Voltage, and the miss in seconds (+ late, - early; None when the word is not in the take)."""
    at = lands_at(words, starts_at, key_word)
    if at is None:
        return f" “{key_word}” is not in the take, so its landing could not be measured.", None
    miss = round(at - beat_at, 3)
    if abs(miss) <= WITHIN:
        return f" “{key_word}” lands at {at:.2f} s, {abs(miss):.2f} s {'after' if miss >= 0 else 'before'} its beat at {beat_at:.2f} s: on the beat.", miss
    move = round(beat_at - (at - starts_at), 2)
    return (f" “{key_word}” lands at {at:.2f} s, {abs(miss):.2f} s {'late' if miss > 0 else 'early'} for its beat at {beat_at:.2f} s; "
            f"start the line at {max(0.0, move):.2f} s, or rewrite it so the word comes {'sooner' if miss > 0 else 'later'}."), miss
