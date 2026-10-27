"""Validation and measurement of an uploaded source video.

The client used to tell us how long its video was. It no longer does: every
number here comes from ffprobe, because the timeline, word snapping and render
manifest are all built on `duration` and a wrong one corrupts all three.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.media import ffmpeg

# Launch (2026-11-04): up to 10 minutes and 2 GB a video. Both can be set
# (AVE_MAX_UPLOAD_SECONDS, AVE_MAX_UPLOAD_MB); every number comes from ffprobe
# and the bytes on disk, never from what the client says.
MAX_SOURCE_SECONDS = float(os.environ.get("AVE_MAX_UPLOAD_SECONDS") or 600.0)
MAX_SOURCE_BYTES = int(float(os.environ.get("AVE_MAX_UPLOAD_MB") or 2048) * 1024 * 1024)


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


def _length(seconds: float) -> str:
    """4 min 05 s, or 45 s."""
    whole = int(round(seconds))
    return f"{whole // 60} min {whole % 60:02d} s" if whole >= 60 else f"{whole} s"


def probe_source(path: str | Path) -> ProbedSource:
    """Measure an uploaded file, or raise IngestError explaining the refusal."""
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegNotInstalled:
        raise
    except ffmpeg.FFmpegError as exc:
        raise IngestError("That file is not a video we can read. Export it again as an MP4 or MOV and upload that.") from exc

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise IngestError("That file has no video track. Upload the video itself, not only its sound.")

    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestError("That video has no readable length. Export it again as an MP4 and upload that.") from exc

    if duration <= 0:
        raise IngestError("That video has no readable length. Export it again as an MP4 and upload that.")
    if duration > MAX_SOURCE_SECONDS:
        raise IngestError(
            f"That video is {_length(duration)} long. Videos can be up to {_length(MAX_SOURCE_SECONDS)} for now; "
            "trim it and upload it again."
        )

    # Run 5 item 4: a video with no audio track is taken (it used to be
    # refused). It has no lines to change, but a voice-over can be placed on
    # it; `add_silent_audio` gives it a silent track before it is stored.

    return ProbedSource(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_fps(video.get("avg_frame_rate")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


# The audio codec each container takes; AVI stays on plain PCM.
_SILENT_CODEC = {"mp4": "aac", "mov": "aac", "mkv": "aac", "webm": "libopus", "avi": "pcm_s16le"}
_MUXER = {"mp4": "mp4", "mov": "mov", "mkv": "matroska", "webm": "webm", "avi": "avi"}


def add_silent_audio(path: str | Path, container: str, duration: float) -> Path:
    """Run 5 item 4: a copy of a video that has no audio track, with a silent
    one, next to it. The picture is copied untouched. With a track, every
    later step (the player, the voice-over mix, the render) treats it like
    any other quiet clip, with no special case."""
    path = Path(path)
    dest = path.with_name(f"with-sound-{path.name}")
    try:
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", "-i", str(path),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", _SILENT_CODEC.get(container, "aac"),
            "-t", f"{duration:.3f}", "-f", _MUXER.get(container, "mp4"), str(dest),
        ])
    except ffmpeg.FFmpegError as exc:
        raise IngestError(
            "That video has no sound, and we could not add a silent track to it. "
            "Export it again as an MP4 and upload that.") from exc
    return dest
