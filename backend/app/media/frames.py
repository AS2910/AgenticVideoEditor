"""Frames of the picture, for Voltage to look at (UX-5, SV-1).

A clip with no speech has nothing for the transcript to show, so the agent
looks at the picture instead: a handful of still frames, evenly spaced, small
enough to send to a model and to show in a strip on the goal stage. Frames are
written once beside the project's media and reused.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.media import ffmpeg

FRAME_WIDTH = 512
# One frame per this many seconds of picture, between MIN and MAX frames,
# never closer than EDGE to either end (the first and last frames of a clip
# are often black or a fade).
SECONDS_PER_FRAME = 2.0
MIN_FRAMES = 3
MAX_FRAMES = 8
EDGE = 0.3


@dataclass(frozen=True)
class Frame:
    at: float      # seconds into the clip
    path: Path     # the JPEG on disk


def frame_times(duration: float) -> list[float]:
    """Where to take frames from a clip of `duration` seconds."""
    if duration <= 0:
        return []
    n = min(MAX_FRAMES, max(MIN_FRAMES, int(duration // SECONDS_PER_FRAME) + 1))
    first = min(EDGE, duration / 2)
    last = max(first, duration - EDGE)
    if n == 1 or last <= first:
        return [round(first, 3)]
    step = (last - first) / (n - 1)
    return [round(first + i * step, 3) for i in range(n)]


def extract_frames(source: str | Path, duration: float, out_dir: str | Path) -> list[Frame]:
    """The clip's frames as JPEGs under `out_dir`, taken once and kept."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, at in enumerate(frame_times(duration)):
        dest = out / f"frame-{i:02d}.jpg"
        if not dest.exists():
            ffmpeg.extract_frame(source, dest, at, width=FRAME_WIDTH)
        frames.append(Frame(at=at, path=dest))
    return frames
