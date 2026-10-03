"""Making a take fit its slot without sounding stretched (Phase 14).

Three small ideas, each cheaper and less audible than stretching speech:

- A **syllable budget**: how many syllables a slot can hold at the speaker's
  own rate. The planner writes to it, so most lines fit before anything is
  voiced.
- **Gap-first fitting**: a take that runs long loses silence first — the
  pauses between words and the lead-in and tail — and only then is sped up,
  within the usual limits. A short take gets its pauses opened a little before
  it is slowed. Speech is stretched less, and a stretched pause is inaudible.
- Measuring the take's own length before anything, so takes can be compared.

Everything here works on the vendor's mono 16-bit WAV at its own rate.
"""
from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.domain.models import Transcript
from app.media import ffmpeg
from app.media.ffmpeg import MAX_TEMPO, MIN_TEMPO, SpanMismatch

# English speech, when nothing is known about the speaker.
DEFAULT_RATE = 4.5          # syllables per second
# How far off the slot a take may be before anything is done to it.
DEFAULT_TOLERANCE = 0.05
# Gaps: a run of frames this quiet, this long, is a pause.
GAP_DB_BELOW_PEAK = 30.0
GAP_FLOOR_DB = -55.0
MIN_GAP_MS = 60
# What a pause may shrink to, and how much it may grow.
KEEP_GAP_MS = 40
KEEP_EDGE_MS = 20
MAX_GROW = 0.6
FRAME_MS = 10

_WORD = re.compile(r"[A-Za-z']+|\d+%?")
_VOWELS = re.compile(r"[aeiouy]+", re.IGNORECASE)


def syllables(text: str) -> int:
    """A rough syllable count: vowel groups per word, a silent final e
    dropped, digits read out. Rough is fine — it sets a budget, not a rule."""
    total = 0
    for token in _WORD.findall(text):
        if token[0].isdigit():
            digits = token.rstrip("%")
            total += max(1, len(digits)) + (2 if token.endswith("%") else 0)
            continue
        word = token.lower().strip("'")
        if not word:
            continue
        n = len(_VOWELS.findall(word))
        if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and n > 1:
            n -= 1
        total += max(1, n)
    return total


def speaking_rate(transcript: Transcript, speaker: str | None = None) -> float:
    """Syllables per second of the speaker's own statements (everyone's, when
    no speaker is given or theirs are too few to trust)."""
    lines = [s for s in transcript.statements if speaker is None or s.speaker == speaker]
    if sum(s.end - s.start for s in lines) < 3.0 and speaker is not None:
        lines = list(transcript.statements)
    seconds = sum(s.end - s.start for s in lines)
    if seconds < 1.0:
        return DEFAULT_RATE
    rate = sum(syllables(s.text) for s in lines) / seconds
    return min(7.0, max(2.5, rate))


def syllable_budget(rate: float, seconds: float) -> int:
    """How many syllables fit in `seconds` at `rate`."""
    return max(1, int(round(rate * seconds)))


@dataclass(frozen=True)
class Gap:
    start: int   # sample index
    end: int


def _read(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "mono 16-bit WAV expected"
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0, rate


def _write(path: str | Path, x: np.ndarray, rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def find_gaps(x: np.ndarray, rate: int) -> list[Gap]:
    """The quiet runs in a take, lead-in and tail included."""
    frame = max(1, int(rate * FRAME_MS / 1000))
    count = len(x) // frame
    if count == 0:
        return []
    frames = x[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    with np.errstate(divide="ignore"):
        db = np.maximum(20 * np.log10(rms), -100.0)
    quiet = (db < db.max() - GAP_DB_BELOW_PEAK) | (db < GAP_FLOOR_DB)
    gaps: list[Gap] = []
    start = None
    for i, q in enumerate(list(quiet) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * FRAME_MS >= MIN_GAP_MS:
                gaps.append(Gap(start * frame, i * frame))
            start = None
    return gaps


def _resize_gaps(x: np.ndarray, rate: int, gaps: list[Gap], delta: int) -> tuple[np.ndarray, int]:
    """Take `delta` samples out of the gaps (delta < 0) or add them in
    (delta > 0), spread in proportion to each gap's size, within limits.
    Returns the new audio and how much was actually moved."""
    if not gaps or delta == 0:
        return x, 0
    n = len(x)
    keep_gap = int(rate * KEEP_GAP_MS / 1000)
    keep_edge = int(rate * KEEP_EDGE_MS / 1000)
    room = []
    for g in gaps:
        size = g.end - g.start
        edge = g.start == 0 or g.end >= n - 1
        if delta < 0:
            room.append(max(0, size - (keep_edge if edge else keep_gap)))
        else:
            room.append(int(size * MAX_GROW))
    total = sum(room)
    if total == 0:
        return x, 0
    move = min(abs(delta), total)
    pieces = []
    cursor = 0
    moved = 0
    for g, r in zip(gaps, room):
        share = int(round(move * r / total))
        pieces.append(x[cursor:g.start])
        gap = x[g.start:g.end]
        if delta < 0:
            cut = min(share, r)
            # Take from the middle of the gap, so the edges stay as they were.
            mid = len(gap) // 2
            gap = np.concatenate([gap[: mid - cut // 2], gap[mid + (cut - cut // 2):]])
            moved += cut
        else:
            grow = min(share, r)
            mid = len(gap) // 2
            fill = np.zeros(grow, dtype=np.float32)
            gap = np.concatenate([gap[:mid], fill, gap[mid:]])
            moved += grow
        pieces.append(gap)
        cursor = g.end
    pieces.append(x[cursor:])
    return np.concatenate(pieces), moved if delta > 0 else -moved


def fit_elastically(
    source: str | Path, dest: str | Path, target: float, tolerance: float = DEFAULT_TOLERANCE,
) -> tuple[Path, float, list[str]]:
    """Fit a take to `target` seconds: pauses first, speech last.

    Within `tolerance` of the target nothing but the final exact trim happens.
    Past it, pauses are shortened (a long take) or opened (a short one), and
    only the remainder is a tempo change, inside the usual MIN/MAX_TEMPO.
    Raises SpanMismatch, with the pause-adjusted length, when even that is
    not enough — the same question as before, asked less often.
    """
    x, rate = _read(source)
    natural = len(x) / rate
    notes: list[str] = []
    dest = Path(dest)
    if abs(natural / target - 1) > tolerance:
        gaps = find_gaps(x, rate)
        wanted = int(round((target - natural) * rate))
        x, moved = _resize_gaps(x, rate, gaps, wanted)
        if moved < 0:
            notes.append(f"trimmed {-moved * 1000 // rate} ms of pauses")
        elif moved > 0:
            notes.append(f"opened the pauses by {moved * 1000 // rate} ms")
    adjusted = len(x) / rate
    tempo = adjusted / target
    if tempo > MAX_TEMPO or adjusted < ffmpeg.MIN_SPEECH_SHARE * target:
        raise SpanMismatch(adjusted, target)
    with_gaps = dest.with_name(dest.stem + ".gaps.wav")
    _write(with_gaps, x, rate)
    try:
        path, duration = ffmpeg.fit_duration(with_gaps, dest, target)
    finally:
        with_gaps.unlink(missing_ok=True)
    if abs(tempo - 1) > tolerance:
        notes.append(f"speech at {max(tempo, MIN_TEMPO):.2f}× speed")
    return path, duration, notes


def place(
    source: str | Path, dest: str | Path, target: float,
    fit: str | None = None, mix: str = "replace", tolerance: float = DEFAULT_TOLERANCE,
) -> tuple[Path, float, list[str]]:
    """`ffmpeg.place`, with the automatic case fitted elastically."""
    if fit is None and mix != "concatenate":
        return fit_elastically(source, dest, target, tolerance)
    path, duration = ffmpeg.place(source, dest, target, fit, mix)
    return path, duration, []
