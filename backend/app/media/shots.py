"""Shot boundaries (Phase 16): where the picture cuts.

A flex or a living hold never crosses a cut — stretching across one would
smear two shots together. ffmpeg's scene score (the change between frames)
past `THRESHOLD` is a cut; the sample ad and phone footage sit well under it
within a shot and well over it at one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from app.media import ffmpeg

THRESHOLD = 0.35
_PTS = re.compile(r"pts_time:\s*([0-9.]+)")


def cuts(path: str | Path, threshold: float = THRESHOLD) -> list[float]:
    """The times, in seconds, at which the picture cuts to another shot."""
    _, err = ffmpeg.run_capture([
        "-hide_banner", "-nostats", "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-",
    ])
    return sorted({round(float(m), 3) for m in _PTS.findall(err)})


def shot_around(at: float, cut_times: Sequence[float], duration: float) -> tuple[float, float]:
    """The shot `at` falls in: from the cut before (or 0) to the cut after (or the end)."""
    start = max([0.0, *[c for c in cut_times if c <= at]])
    end = min([duration, *[c for c in cut_times if c > at]])
    return start, end
