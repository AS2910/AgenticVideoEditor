"""Real rendering (Phase 7): the source video, re-voiced where edits were approved.

The video frames are the source's own, everywhere. Lip-sync is backlogged
(Phase 5) and the mock "frames" are a flat colour, so splicing those in would
make the export worse; until real lip-sync lands, the mouth will not match the
new words. `use_generated_frames` is where Phase 5 switches that on.

Audio is decoded at 48 kHz in the source's own channel layout, each edited
span is replaced by its edit's audio, and every seam gets a short equal-power
crossfade *inside* the span — so everything outside an edit stays exactly the
source's audio.
"""
from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

from app.domain.models import Source
from app.media import ffmpeg
from app.render.renderer import RenderSegment

OUT_RATE = 48000
CROSSFADE = 0.02     # seconds per seam
AUDIO_BITRATE = "192k"
# Codecs that play in every browser inside MP4. Anything else is re-encoded.
_COPYABLE_VIDEO = {"h264"}


def _channels(path: str | Path) -> int:
    streams = ffmpeg.probe(path)["streams"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    return min(int(audio[0].get("channels", 1)), 2) if audio else 1


def decode(path: str | Path, channels: int | None = None) -> np.ndarray:
    """Audio as float32 of shape (samples, channels) at OUT_RATE."""
    channels = channels or _channels(path)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "a.wav"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", "-i", str(path), "-vn",
            "-ac", str(channels), "-ar", str(OUT_RATE), "-c:a", "pcm_s16le", str(dest),
        ])
        with wave.open(str(dest), "rb") as w:
            raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return samples.reshape(-1, channels)


def _write(path: Path, x: np.ndarray) -> None:
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(OUT_RATE)
        w.writeframes(pcm.tobytes())


def splice(base: np.ndarray, segments: Sequence[RenderSegment]) -> np.ndarray:
    """Replace each edited span of `base` with its edit's audio, crossfaded."""
    out = base.copy()
    channels = base.shape[1]
    cache: dict[str, np.ndarray] = {}
    for seg in segments:
        if seg.kind != "edited" or seg.edit is None:
            continue
        i0 = min(round(seg.start * OUT_RATE), len(out))
        i1 = min(round(seg.end * OUT_RATE), len(out))
        length = i1 - i0
        if length <= 0:
            continue
        edit = seg.edit
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        audio = cache[edit.audio.sha256]
        # A span may be only the tail of its edit (a later approval took the
        # head), so start reading the edit's audio at the matching offset.
        offset = round((seg.start - edit.plan.selection.start) * OUT_RATE)
        piece = audio[offset:offset + length]
        if len(piece) < length:
            piece = np.pad(piece, ((0, length - len(piece)), (0, 0)))

        fade = min(round(CROSSFADE * OUT_RATE), length // 2)
        new = np.ones(length, dtype=np.float32)
        if fade:
            ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))
            new[:fade] = ramp
            new[-fade:] = ramp[::-1]
        old = np.sqrt(np.maximum(0.0, 1.0 - new ** 2))  # equal power
        out[i0:i1] = base[i0:i1] * old[:, None] + piece * new[:, None]
    return out


def _video_codec(path: str | Path) -> str | None:
    for stream in ffmpeg.probe(path)["streams"]:
        if stream.get("codec_type") == "video":
            return stream.get("codec_name")
    return None


def compose(
    source: Source,
    segments: Sequence[RenderSegment],
    dest: str | Path,
    use_generated_frames: bool = False,
) -> Path:
    """Write the edited video to `dest` (MP4, H.264 + AAC)."""
    if use_generated_frames:
        raise NotImplementedError("Compositing generated frames arrives with real lip-sync (Phase 5).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    video_args = (
        ["-c:v", "copy"] if _video_codec(source.media.path) in _COPYABLE_VIDEO
        else ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18"]
    )
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        _write(audio, splice(decode(source.media.path), segments))
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN,
            "-i", str(source.media.path), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", *video_args,
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart", *ffmpeg._BITEXACT_OUT, str(dest),
        ])
    return dest
