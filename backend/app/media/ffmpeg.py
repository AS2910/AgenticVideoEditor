"""Thin, deterministic wrapper around the ffmpeg/ffprobe CLIs.

Phase 0 needs three things from ffmpeg: probe a file's real duration, make
silence, and make black frames. Phase 1 (ingest) and Phase 7 (render) build on
`probe()` and `run()` rather than reinventing the subprocess handling.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import wave
from pathlib import Path

from app.errors import NonRetryableError

FFMPEG = os.environ.get("AVE_FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("AVE_FFPROBE_BIN", "ffprobe")

# Strips encoder banners, creation timestamps and other ambient metadata so
# identical inputs yield byte-identical output. The artifact store is
# content-addressed, so this is load-bearing, not cosmetic. `-fflags` has to
# precede the input; the rest apply to the output.
_BITEXACT_IN = ("-fflags", "+bitexact")
_BITEXACT_OUT = ("-flags", "+bitexact", "-map_metadata", "-1")


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe exited non-zero."""


class FFmpegNotInstalled(FFmpegError):
    """The binary is not on PATH."""


# How far generated speech may be sped up or slowed down to fill a selection.
# Beyond this it audibly sounds rushed or dragged, so the edit is refused.
MIN_TEMPO = 0.8
MAX_TEMPO = 1.25
# A line shorter than the selection is slowed by at most MIN_TEMPO and the rest
# padded with silence, split both sides — a short pause sounds natural where
# over-stretched speech does not. Below this share of the span it is refused.
MIN_SPEECH_SHARE = 0.6


class SpanMismatch(NonRetryableError):
    """Generated speech is too long or too short to fit the selection."""

    def __init__(self, natural: float, target: float) -> None:
        self.natural = natural
        self.target = target
        if natural > target:
            advice = "The new line is too long for the selection — widen the selection or shorten the line."
        else:
            advice = "The new line is too short for the selection — narrow the selection or lengthen the line."
        super().__init__(f"{advice} (needs {natural:.2f}s, selection is {target:.2f}s)")


def available() -> bool:
    """True when both binaries are callable. Lets callers pick a fallback."""
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def _run(binary: str, args: list[str]) -> str:
    if shutil.which(binary) is None:
        raise FFmpegNotInstalled(
            f"{binary!r} is not on PATH. Install it with `brew install ffmpeg`."
        )
    proc = subprocess.run([binary, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-5:]
        raise FFmpegError(f"{binary} exited {proc.returncode}: {' / '.join(tail)}")
    return proc.stdout


def probe(path: str | Path) -> dict:
    """ffprobe's format + streams JSON for a media file."""
    out = _run(FFPROBE, [
        "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
    ])
    return json.loads(out)


def duration_of(path: str | Path) -> float:
    """Actual encoded duration in seconds, straight from the container."""
    return float(probe(path)["format"]["duration"])


def generate_silence(
    dest: str | Path, duration: float, sample_rate: int = 16000,
) -> tuple[Path, float]:
    """Write a silent mono WAV. Returns (path, true encoded duration)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN,
        "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=mono",
        "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)


def extract_audio(
    source: str | Path, dest: str | Path, sample_rate: int = 16000,
) -> tuple[Path, float]:
    """Pull a mono WAV out of a video, ready for transcription.

    16 kHz mono is what speech models want, and it keeps the upload small.
    Raises FFmpegError if the input has no audio stream.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN, "-i", str(source),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)


def generate_tone(
    dest: str | Path, duration: float, frequency: float, sample_rate: int = 16000,
) -> tuple[Path, float]:
    """Write a mono sine-tone WAV. Returns (path, true encoded duration).

    Used by the mock voice adapter: a tone keyed to the spoken text keeps mock
    output *input-sensitive*, which plain silence would not be.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN,
        "-f", "lavfi", "-i", f"sine=frequency={frequency:.2f}:sample_rate={sample_rate}",
        "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)


def generate_solid_video(
    dest: str | Path, duration: float, color: str = "black",
    fps: int = 25, size: str = "320x180",
) -> tuple[Path, float]:
    """Write a solid-colour H.264 MP4. Returns (path, true encoded duration).

    `color` is any ffmpeg colour spec — a name, or `0xRRGGBB`.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN,
        "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}",
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)


def pcm_to_wav(
    pcm: bytes, dest: str | Path, sample_rate: int,
) -> tuple[Path, float]:
    """Wrap raw little-endian s16 mono samples (a vendor response) as a WAV."""
    if not pcm:
        raise FFmpegError("no audio samples to write")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return dest, duration_of(dest)


def fit_duration(
    source: str | Path, dest: str | Path, target: float,
) -> tuple[Path, float]:
    """Fit speech to exactly `target` seconds, pitch unchanged.

    Too long: sped up by at most MAX_TEMPO, else SpanMismatch.
    Too short: slowed by at most MIN_TEMPO, then centred in silence — refused
    only if the speech would fill less than MIN_SPEECH_SHARE of the span.
    `-t` makes the length exact rather than approximately right, so the
    spliced audio covers the selection and nothing past it.
    """
    natural = duration_of(source)
    tempo = natural / target
    if tempo > MAX_TEMPO:
        raise SpanMismatch(natural, target)
    tempo = max(tempo, MIN_TEMPO)
    speech = natural / tempo
    if speech < MIN_SPEECH_SHARE * target:
        raise SpanMismatch(natural, target)
    lead_ms = int((target - speech) / 2 * 1000)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN, "-i", str(source),
        "-af", f"atempo={tempo:.6f},adelay={lead_ms}:all=1,apad", "-t", f"{target:.3f}",
        "-c:a", "pcm_s16le", *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)


def extract_segment(
    source: str | Path, dest: str | Path, start: float, end: float,
    sample_rate: int = 16000,
) -> tuple[Path, float]:
    """Cut [start, end) out of any media file as a mono WAV."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(FFMPEG, [
        "-y", "-loglevel", "error", *_BITEXACT_IN, "-i", str(source),
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        *_BITEXACT_OUT, str(dest),
    ])
    return dest, duration_of(dest)
