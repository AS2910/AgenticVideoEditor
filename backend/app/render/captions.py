"""B3: captions for a delivered file, from the words as the video says them
now: every transcript line no shipped edit replaced or removed, plus every
shipped edit's words, each placed where it plays in the render (the render's
pieces map source time to output time: a flexed line stretches, an added
line plays in its hold).

    cues(passages, pieces)  -> [Cue]   in output time, split to two short lines each
    srt(cues)               -> str     SubRip, for ffmpeg's subtitles filter

Burning them in is app/render/deliver.py's job.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

# About two lines of a phone-width caption.
MAX_CHARS = 42
MAX_LINES = 2


@dataclass(frozen=True)
class Passage:
    """Words said in the source's time: a transcript line or a shipped edit."""
    text: str
    start: float
    end: float
    added: bool = False           # an added line that plays in a hold (the picture makes room)
    duration: float | None = None  # the take's own length, for a line laid over the picture


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def out_time(t: float, pieces: Sequence[dict] | None, end: bool = False) -> float:
    """Where a moment of the source plays in the render (holds add time, flexes
    stretch it). On a boundary between pieces a start is placed in the piece
    that begins there (after any hold) and an `end` in the one that ends there."""
    if not pieces:
        return t
    for p in pieces:
        if p["kind"] == "hold" or p["end"] <= p["start"]:
            continue
        inside = (p["start"] - 1e-6 < t <= p["end"] + 1e-6) if end else (p["start"] - 1e-6 <= t < p["end"] - 1e-6)
        if inside:
            share = (t - p["start"]) / (p["end"] - p["start"])
            return p["out_start"] + min(1.0, max(0.0, share)) * (p["out_end"] - p["out_start"])
    last = max((p for p in pieces if p["kind"] != "hold"), key=lambda p: p["end"], default=None)
    if last is not None and t >= last["end"] - 1e-6:
        return last["out_end"] + (t - last["end"])
    return t


def _hold_at(t: float, pieces: Sequence[dict] | None) -> dict | None:
    for p in pieces or ():
        if p["kind"] == "hold" and abs(p["start"] - t) <= 0.05:
            return p
    return None


def wrap(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Words into lines of at most `max_chars` (a longer word stands alone)."""
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _split(start: float, end: float, text: str) -> list[Cue]:
    """One passage as cues of at most two lines, its time shared by characters."""
    lines = wrap(text)
    if not lines:
        return []
    groups = [tuple(lines[i:i + MAX_LINES]) for i in range(0, len(lines), MAX_LINES)]
    total = sum(len(" ".join(g)) for g in groups) or 1
    out, at = [], start
    for g in groups:
        span = (end - start) * len(" ".join(g)) / total
        out.append(Cue(round(at, 3), round(at + span, 3), g))
        at += span
    return out


def cues(passages: Sequence[Passage], pieces: Sequence[dict] | None = None, min_seconds: float = 0.6) -> list[Cue]:
    """Every passage in output time, in order, none overlapping the next."""
    placed: list[tuple[float, float, str]] = []
    for p in passages:
        text = " ".join(p.text.split())
        if not text:
            continue
        hold = _hold_at(p.start, pieces) if p.added else None
        if hold is not None:
            start, end = hold["out_start"], hold["out_end"]
        else:
            start = out_time(p.start, pieces)
            end = out_time(p.end, pieces, end=True) if p.end > p.start else start
            if p.duration:
                end = max(end, start + p.duration)
        placed.append((start, max(end, start + min_seconds), text))
    placed.sort(key=lambda x: x[0])
    out: list[Cue] = []
    for i, (start, end, text) in enumerate(placed):
        if i + 1 < len(placed):
            end = min(end, placed[i + 1][0])
        if end - start < 0.05:
            continue
        out.extend(_split(start, end, text))
    return out


def _stamp(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(items: Sequence[Cue]) -> str:
    return "".join(f"{n}\n{_stamp(c.start)} --> {_stamp(c.end)}\n{c.text}\n\n" for n, c in enumerate(items, 1))


def latin_only(texts: Iterable[str]) -> bool:
    """9c: every letter is a Latin one (accents allowed). Hindi, Tamil and
    other scripts need libass to be drawn; OpenCV's font would draw boxes."""
    for text in texts:
        for ch in text:
            if ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN"):
                return False
    return True
