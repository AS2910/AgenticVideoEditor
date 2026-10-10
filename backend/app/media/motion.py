"""How much the picture moves (Phase 16), chunk by chunk.

Time added to a window should go where the picture moves least — a slowed
still face is invisible, a slowed hand wave is not. The measure is the mean
absolute difference between consecutive frames of a tiny grey decode (64×36
at 10 fps), averaged over each chunk. Units are arbitrary (0–255 grey levels);
only the ratios between chunks matter.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from app.media import ffmpeg

CHUNK = 0.25     # seconds per chunk
FPS = 10
W, H = 64, 36


def chunk_count(seconds: float, chunk: float = CHUNK) -> int:
    return max(1, int(math.ceil(seconds / chunk - 1e-6)))


def frames(path: str | Path, start: float, end: float) -> np.ndarray:
    """Grey frames of [start, end) as (n, H*W) float32."""
    out, _ = ffmpeg.run_capture([
        "-hide_banner", "-nostats", "-loglevel", "error",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.0, end - start):.3f}", "-i", str(path),
        "-vf", f"scale={W}:{H},fps={FPS},format=gray", "-f", "rawvideo", "-",
    ], text=False)
    raw = np.frombuffer(out, dtype=np.uint8)
    n = len(raw) // (W * H)
    return raw[: n * W * H].reshape(n, W * H).astype(np.float32)


def motion(path: str | Path, start: float, end: float, chunk: float = CHUNK) -> list[float]:
    """One motion figure per chunk of [start, end); zeros when there are too
    few frames to compare."""
    n = chunk_count(end - start, chunk)
    x = frames(path, start, end)
    if len(x) < 2:
        return [0.0] * n
    diffs = np.abs(np.diff(x, axis=0)).mean(axis=1)          # one per frame pair
    per_chunk = max(1, int(round(chunk * FPS)))
    out = []
    for i in range(n):
        part = diffs[i * per_chunk:(i + 1) * per_chunk]
        out.append(float(part.mean()) if part.size else (out[-1] if out else 0.0))
    return out
