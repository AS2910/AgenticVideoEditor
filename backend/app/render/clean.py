"""Clean joins (run 5 addendum 3, item 1).

Where a new take meets the original, three things decide whether anyone hears
the edit:

- **where** the cut falls: on a zero crossing, or in silence, so the two
  waveforms meet near zero and nothing steps. A join may move inward by at
  most `SNAP` seconds to find one; it never moves outside its span, so
  everything outside an edit stays the source's own audio, bit for bit;
- **how long** the crossfade is: 10 to 30 ms, equal power. Short (10 ms) when
  both sides are quiet there, long (30 ms) when the levels differ a lot, 20 ms
  otherwise;
- **what plays in a gap**: a take is often shorter than its span (the fit
  centres it in silence) and has pauses of its own. Digital silence in the
  middle of a room is a hole; the room's own tone, read from the quiet parts of
  the original around the span and looped with crossfades, plays under any
  part of the take quieter than that room.

Pure numpy; `render.compose.splice` calls it.
"""
from __future__ import annotations

import numpy as np

JOIN_MIN = 0.010           # seconds: the shortest crossfade
JOIN_MID = 0.020
JOIN_MAX = 0.030           # the longest
SNAP = 0.008               # how far inward a join may move to meet a zero crossing or silence
QUIET_DB = -50.0           # both sides this quiet at a join: the short crossfade
STEP_DB = 6.0              # levels this far apart either side: the long one
ROOM_READ = 3.0            # seconds of the original either side the room tone is read from
GAP_BELOW_ROOM = 0.5       # a take quieter than half the room's level (-6 dB) is a gap there
FRAME = 0.01


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    return float(20 * np.log10(max(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))), 1e-6)))


def snap(old: np.ndarray, new: np.ndarray, at: int, direction: int, limit: int) -> int:
    """The sample, from `at` up to `limit` samples in `direction` (+1 inward
    from a span's start, -1 inward from its end), where both signals sit
    nearest zero: a shared zero crossing, or silence. `old` and `new` are mono
    and indexed alike."""
    n = min(len(old), len(new))
    if limit <= 0 or n == 0:
        return at
    lo, hi = (at, min(n - 1, at + limit)) if direction > 0 else (max(0, at - limit), min(n - 1, at))
    if hi <= lo:
        return at
    score = np.abs(old[lo:hi + 1]) + np.abs(new[lo:hi + 1])
    best = int(np.argmin(score))
    # Ties (a run of silence): the point nearest the original join.
    ties = np.flatnonzero(score <= score[best] + 1e-7)
    pick = ties[0] if direction > 0 else ties[-1]
    return lo + int(pick)


def fade_length(old: np.ndarray, new: np.ndarray, rate: int) -> int:
    """10 to 30 ms, from the levels either side of the join (mono windows)."""
    a, b = _rms_db(old), _rms_db(new)
    if a < QUIET_DB and b < QUIET_DB:
        return int(round(JOIN_MIN * rate))
    if abs(a - b) > STEP_DB:
        return int(round(JOIN_MAX * rate))
    return int(round(JOIN_MID * rate))


TONE_SECONDS = 0.3         # the stretch of room read and looped


def room_tone(source: np.ndarray, rate: int) -> np.ndarray:
    """The quietest unbroken stretch of `source` (mono), up to TONE_SECONDS:
    the room with no one talking. One stretch, not frames picked apart, so the
    loop has no step inside it."""
    frame = max(1, int(rate * FRAME))
    count = len(source) // frame
    if count < 5:
        return np.zeros(0, dtype=np.float32)
    frames = source[: count * frame].reshape(count, frame)
    power = (frames.astype(np.float64) ** 2).mean(axis=1)
    width = max(1, min(int(TONE_SECONDS / FRAME), count // 2))
    sums = np.convolve(power, np.ones(width), mode="valid")
    at = int(np.argmin(sums))
    return source[at * frame:(at + width) * frame].astype(np.float32)


def gap_fill(take: np.ndarray, tone: np.ndarray, rate: int) -> np.ndarray:
    """Room tone for the parts of `take` (mono) quieter than the room, looped
    and faded in and out with 10 ms ramps; zeros where the take is louder."""
    from app.continuity.measured import loop_room   # one loop, the same as the take's own room tone
    n = len(take)
    if n == 0 or tone.size == 0:
        return np.zeros(n, dtype=np.float32)
    level = float(np.sqrt(np.mean(tone.astype(np.float64) ** 2)))
    if level <= 1e-5:
        return np.zeros(n, dtype=np.float32)
    frame = max(1, int(rate * FRAME))
    count = -(-n // frame)
    padded = np.pad(take, (0, count * frame - n))
    rms = np.sqrt((padded.reshape(count, frame).astype(np.float64) ** 2).mean(axis=1))
    gap = (rms < level * GAP_BELOW_ROOM).astype(np.float32)
    if not gap.any():
        return np.zeros(n, dtype=np.float32)
    # Frame mask to samples, smoothed so the room fades in and out of each gap.
    env = np.repeat(gap, frame)[:n]
    k = frame
    kernel = np.ones(k, dtype=np.float32) / k
    env = np.convolve(env, kernel, mode="same").astype(np.float32)
    return loop_room(tone, n, rate) * env


def tone_around(source: np.ndarray, i0: int, i1: int, rate: int) -> np.ndarray:
    """The room tone of the original either side of [i0, i1) (mono)."""
    reach = int(ROOM_READ * rate)
    window = np.concatenate([source[max(0, i0 - reach):i0], source[i1:i1 + reach]])
    return room_tone(window, rate)
