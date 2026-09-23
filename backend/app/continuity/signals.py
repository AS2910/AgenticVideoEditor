"""Measurements of speech audio, for the continuity checks (Phase 6a).

Everything works on mono 16 kHz float32 in [-1, 1]. The numbers are simple and
explainable on purpose — a level in dBFS, a median pitch in Hz, words per
second — so a failing score can be traced to something a person can hear.
"""
from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

from app.media import ffmpeg

RATE = 16000
FRAME = 320          # 20 ms, for levels
PITCH_FRAME = 640    # 40 ms: two periods of the lowest pitch we look for
HOP = 160            # 10 ms
FLOOR_DB = -100.0    # what digital silence reads as, instead of -inf

F0_MIN, F0_MAX = 75.0, 400.0   # covers adult speech, low male to high female
VOICING = 0.5                  # normalised autocorrelation needed to call a frame voiced
ACTIVE_RANGE_DB = 30.0         # a frame is speech if within this of the loudest frame
SILENCE_DB = -60.0             # ...and louder than this


def load(
    path: str | Path, start: float | None = None, end: float | None = None,
    rate: int = RATE,
) -> np.ndarray:
    """Decode any media file (or a span of it) to mono float32, 16 kHz by default."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "x.wav"
        if start is None:
            ffmpeg.extract_audio(path, dest, sample_rate=rate)
        else:
            ffmpeg.extract_segment(path, dest, start, end, sample_rate=rate)
        with wave.open(str(dest), "rb") as w:
            raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _frames(x: np.ndarray, size: int) -> np.ndarray:
    if len(x) < size:
        return np.empty((0, size), dtype=np.float32)
    count = 1 + (len(x) - size) // HOP
    index = np.arange(size)[None, :] + HOP * np.arange(count)[:, None]
    return x[index]


def _to_db(rms: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return np.maximum(20 * np.log10(rms), FLOOR_DB)


def frame_levels_db(x: np.ndarray) -> np.ndarray:
    frames = _frames(x, FRAME)
    return _to_db(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)))


def _active(levels: np.ndarray) -> np.ndarray:
    if levels.size == 0:
        return np.zeros(0, dtype=bool)
    return (levels >= levels.max() - ACTIVE_RANGE_DB) & (levels > SILENCE_DB)


def speech_level_db(x: np.ndarray) -> float | None:
    """RMS level of the speech itself, ignoring pauses and silence."""
    frames = _frames(x, FRAME)
    levels = frame_levels_db(x)
    active = _active(levels)
    if not active.any():
        return None
    power = np.mean(frames[active].astype(np.float64) ** 2)
    return float(_to_db(np.sqrt(np.array([power])))[0])


def noise_floor_db(x: np.ndarray) -> float:
    """Level of the quietest tenth of the audio — the room under the speech."""
    levels = frame_levels_db(x)
    if levels.size == 0:
        return FLOOR_DB
    return float(np.percentile(levels, 10))


def median_f0(x: np.ndarray) -> float | None:
    """Median pitch (Hz) over voiced frames, or None if too little is voiced."""
    frames = _frames(x, PITCH_FRAME).astype(np.float64)
    if frames.shape[0] == 0:
        return None
    frames -= frames.mean(axis=1, keepdims=True)
    energy = np.sum(frames ** 2, axis=1)
    keep = _active(_to_db(np.sqrt(energy / PITCH_FRAME)))
    frames = frames[keep]
    if frames.shape[0] == 0:
        return None

    lags = np.arange(int(RATE / F0_MAX), int(RATE / F0_MIN) + 2)
    corr = np.empty((frames.shape[0], lags.size))
    for i, lag in enumerate(lags):
        a, b = frames[:, :-lag], frames[:, lag:]
        denom = np.sqrt(np.sum(a * a, axis=1) * np.sum(b * b, axis=1))
        corr[:, i] = np.sum(a * b, axis=1) / np.where(denom > 0, denom, np.inf)

    pitches = []
    for row in corr:
        peak = row.max()
        if peak < VOICING:
            continue
        # The first lag close to the best peak is the fundamental; later near-
        # equal peaks are its multiples (the classic octave error).
        candidates = np.flatnonzero(row >= 0.9 * peak)
        i = candidates[0]
        while i + 1 < row.size and row[i + 1] > row[i]:
            i += 1  # climb to the local maximum
        lag = float(lags[i])
        if 0 < i < row.size - 1:  # parabolic interpolation for sub-sample accuracy
            y0, y1, y2 = row[i - 1], row[i], row[i + 1]
            denom = y0 - 2 * y1 + y2
            if denom != 0:
                lag += 0.5 * (y0 - y2) / denom
        pitches.append(RATE / lag)
    if len(pitches) < 3:
        return None
    return float(np.median(pitches))


def words_per_second(text: str, seconds: float) -> float | None:
    words = len(text.split())
    if words == 0 or seconds <= 0:
        return None
    return words / seconds
