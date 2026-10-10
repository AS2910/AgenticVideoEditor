"""The seam: how much the sound jumps where an edit meets the original (Phase 19).

A pasted line gives itself away at its edges — a step in level, a change of
colour — before anyone hears the words. Two numbers per seam, each from a
short window either side of it:

- **level**, the RMS step in dB;
- **colour**, the spectral centroid's step in semitones.

Both are zero for a seam no one would notice and grow with the jump. They are
measured on the *rendered* export, so they include the crossfade and whatever
room tone and level correction the engine applied — what the viewer hears.

A line's own edges step too — speech starts after a pause — so the number
that matters is the step *relative to the original* at the same point: the
render's step minus the original's. `discontinuity` is that difference.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

WINDOW = 0.05   # seconds either side of the seam


@dataclass(frozen=True)
class SeamJump:
    at: float
    level_db: float
    centroid_semitones: float


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -100.0
    return 20 * math.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-5))


def _centroid_hz(x: np.ndarray, rate: int) -> float | None:
    if x.size < 16:
        return None
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    total = float(spectrum.sum())
    if total <= 1e-9:
        return None
    freqs = np.fft.rfftfreq(x.size, 1 / rate)
    return float((spectrum * freqs).sum() / total)


def seam_jumps(x: np.ndarray, rate: int, seams: Sequence[float], window: float = WINDOW) -> list[SeamJump]:
    """The level and colour step across each seam of `x` (mono or (n, ch))."""
    mono = _mono(x)
    half = max(1, int(window * rate))
    out: list[SeamJump] = []
    for at in seams:
        i = int(round(at * rate))
        before = mono[max(0, i - half):i]
        after = mono[i:i + half]
        level = abs(_rms_db(after) - _rms_db(before))
        cb, ca = _centroid_hz(before, rate), _centroid_hz(after, rate)
        colour = abs(12 * math.log2(ca / cb)) if cb and ca and cb > 0 and ca > 0 else 0.0
        out.append(SeamJump(at=at, level_db=level, centroid_semitones=colour))
    return out


def discontinuity(
    rendered: np.ndarray, original: np.ndarray, rate: int,
    seams: Sequence[float], original_seams: Sequence[float] | None = None, window: float = WINDOW,
) -> list[SeamJump]:
    """How much more (or differently) the render steps at each seam than the
    original does at the matching point — the part of the step the edit added.
    `original_seams` maps each render seam to its point in the original (the
    same times, unless the render is longer than the source)."""
    original_seams = list(original_seams) if original_seams is not None else list(seams)
    ours = seam_jumps(rendered, rate, seams, window)
    theirs = seam_jumps(original, rate, original_seams, window)
    return [SeamJump(at=a.at, level_db=abs(a.level_db - b.level_db),
                     centroid_semitones=abs(a.centroid_semitones - b.centroid_semitones))
            for a, b in zip(ours, theirs)]


def worst(jumps: Sequence[SeamJump]) -> tuple[float, float]:
    """The largest level and colour step among the seams (0, 0 when none)."""
    if not jumps:
        return 0.0, 0.0
    return max(j.level_db for j in jumps), max(j.centroid_semitones for j in jumps)
