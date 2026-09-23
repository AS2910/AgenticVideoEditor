"""Validation and measurement of an uploaded source video.

The client used to tell us how long its video was. It no longer does: every
number here comes from ffprobe, because the timeline, word snapping and render
manifest are all built on `duration` and a wrong one corrupts all three.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.media import ffmpeg

# Design spec §2: short-form only, ~2–3 minutes, to hold quality and keep
# cost and latency sane once real vendors are in the loop.
MAX_SOURCE_SECONDS = 180.0

# A blunt guard against filling the disk. The duration cap is the real limit;
# this only catches absurd files before we finish writing them.
MAX_SOURCE_BYTES = 500 * 1024 * 1024


class IngestError(ValueError):
    """An upload we refuse, carrying a reason fit to show the user."""


@dataclass(frozen=True)
class ProbedSource:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def _fps(rate: str | None) -> float:
    """ffprobe reports frame rates as fractions like '30000/1001'."""
    if not rate or "/" not in rate:
        return 0.0
    numerator, _, denominator = rate.partition("/")
    try:
        den = float(denominator)
        return float(numerator) / den if den else 0.0
    except ValueError:
        return 0.0


def probe_source(path: str | Path) -> ProbedSource:
    """Measure an uploaded file, or raise IngestError explaining the refusal."""
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegNotInstalled:
        raise
    except ffmpeg.FFmpegError as exc:
        raise IngestError("That file is not a video we can read.") from exc

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise IngestError("That file has no video track.")

    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestError("That video has no readable duration.") from exc

    if duration <= 0:
        raise IngestError("That video has no readable duration.")
    if duration > MAX_SOURCE_SECONDS:
        raise IngestError(
            f"That video is {duration:.0f}s long. "
            f"The limit is {MAX_SOURCE_SECONDS:.0f}s for now."
        )

    if not any(s.get("codec_type") == "audio" for s in streams):
        # A dialogue editor has nothing to work with: no audio means no speech
        # to transcribe, no voice to clone, and no line to change.
        raise IngestError("That video has no audio track, so there is no dialogue to edit.")

    return ProbedSource(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_fps(video.get("avg_frame_rate")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )
