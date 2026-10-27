"""The lip-sync seam (Run 5, item 10): no provider is chosen yet.

A `LipSyncProvider` takes a short piece of the source picture and the new
audio for it, and returns that piece with the mouth re-drawn. Only the changed
span is ever sent, widened by `HANDLE` seconds each side (kept inside the clip
and inside its shot) so the model has a run-up and the join is not on the
first changed frame; the result is laid back into the source picture frame for
frame (`stitch`). The rest of the clip never leaves the machine.

Providers:
- `fake` (`lipsync/fake.py`): for tests and the review page; free, instant,
  the source span with the new audio and a visible marker, so a stitch is
  easy to see.
- `sync_so` (`lipsync/vendor.py`): the hosted API, measured in Phase 17's spike.
- `selfhosted` (`lipsync/selfhosted.py`): an open model (LatentSync) behind an
  HTTP endpoint we would run on our own GPU.

Both real ones are off unless `AVE_LIPSYNC_PROVIDER` names them AND their key
or endpoint is set; tests blank both. LIPSYNC.md compares them.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.media import ffmpeg

HANDLE = 0.5      # seconds of run-up and run-out either side of the changed span
MIN_SPAN = 0.4    # a vendor refuses a clip shorter than this (Phase 17's spike)


class LipSyncUnavailable(RuntimeError):
    """The provider is off (no key, no endpoint) or cannot do this clip."""


@dataclass(frozen=True)
class Window:
    """What is sent: the changed span [start, end) inside the sent window
    [send_start, send_end) (the span plus its handles)."""
    start: float
    end: float
    send_start: float
    send_end: float

    @property
    def seconds(self) -> float:
        return self.send_end - self.send_start

    @property
    def lead(self) -> float:
        """Seconds of handle before the span inside the window."""
        return self.start - self.send_start


@dataclass(frozen=True)
class SpanRequest:
    """One provider call: the source window as a file, and the audio that
    should be on it (the window's length: the original sound in the handles,
    the new take over the span)."""
    clip: Path
    audio: Path
    window: Window
    seconds: float


@dataclass(frozen=True)
class SpanResult:
    clip: Path                 # the window with the mouth re-drawn, same length and frame rate
    provider: str
    usd: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)


class LipSyncProvider(Protocol):
    name: str

    def available(self) -> bool:
        """True when it can be called now (key or endpoint set, switched on)."""
        ...

    def usd_for(self, seconds: float) -> float:
        """What `seconds` of video would cost, before anything is sent."""
        ...

    def sync_span(self, request: SpanRequest, dest: Path) -> SpanResult:
        """Re-draw the mouth in `request.clip` to `request.audio`, written to `dest`."""
        ...


def window(start: float, end: float, duration: float, cuts: Sequence[float] = (), handle: float = HANDLE) -> Window:
    """The span widened by `handle` each side, kept inside the clip and never
    across a cut (a handle in another shot would show the model a different
    face)."""
    if end <= start:
        raise ValueError("the span is empty")
    lo = max(0.0, start - handle, *[c for c in cuts if c <= start])
    hi = min(duration, end + handle, *[c for c in cuts if c >= end])
    return Window(round(start, 3), round(end, 3), round(lo, 3), round(hi, 3))


def cut_window(source: Path, w: Window, dest: Path) -> Path:
    """The window of the source as its own file, re-encoded so it starts on a
    frame (a stream copy would start on the previous keyframe)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-ss", f"{w.send_start:.3f}", "-i", str(source), "-t", f"{w.seconds:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "16",
        "-c:a", "aac", "-movflags", "+faststart", str(dest),
    ])
    return dest


def window_audio(source: Path, take: Path, w: Window, dest: Path) -> Path:
    """The window's sound as the provider should hear it: the source's own in
    the handles, the take over the span (cut or padded with silence to fit)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    span = w.end - w.start
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error",
        "-ss", f"{w.send_start:.3f}", "-t", f"{w.seconds:.3f}", "-i", str(source),
        "-i", str(take),
        "-filter_complex",
        f"[0:a]aformat=sample_rates=16000:channel_layouts=mono,"
        f"volume=enable='between(t,{w.lead:.3f},{w.lead + span:.3f})':volume=0[bed];"
        f"[1:a]aformat=sample_rates=16000:channel_layouts=mono,atrim=0:{span:.3f},apad=whole_dur={span:.3f},"
        f"adelay={int(w.lead * 1000)}:all=1[new];"
        f"[bed][new]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "[a]", "-c:a", "pcm_s16le", str(dest),
    ])
    return dest


def stitch(source: Path, w: Window, synced: Path, dest: Path) -> Path:
    """The source picture with the synced window laid in frame for frame and
    the source's soundtrack copied through (the mix lays the take in, as it
    always has). Reuses Phase 17's frame-exact patch graph."""
    from app.lipsync.patch import patch_graph
    info = ffmpeg.probe(source)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = int(video["width"]), int(video["height"])
    fps = ffmpeg.frame_rate(source)
    total = round(float(info["format"]["duration"]) * fps)
    span = (round(w.send_start * fps), min(total, round(w.send_end * fps)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(source), "-i", str(synced),
        "-filter_complex", patch_graph([span], total, width, height, fps),
        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-crf", "16", "-c:a", "copy", "-movflags", "+faststart", str(dest),
    ])
    return dest


def replace_span(
    provider: LipSyncProvider, source: Path, take: Path, start: float, end: float, duration: float,
    work: Path, cuts: Sequence[float] = (), stitched: Path | None = None,
) -> tuple[Window, SpanResult, Path | None]:
    """The whole round trip for one changed span: widen it, cut the window and
    its audio, call the provider, and (when `stitched` is given) lay the result
    back into the full picture. Raises LipSyncUnavailable when the provider is
    off or the span is too short to send."""
    if not provider.available():
        raise LipSyncUnavailable(f"Lip-sync ({provider.name}) is off.")
    w = window(start, end, duration, cuts)
    if w.end - w.start < MIN_SPAN:
        raise LipSyncUnavailable("This line is too short to re-draw the mouth on.")
    work.mkdir(parents=True, exist_ok=True)
    clip = cut_window(source, w, work / "window.mp4")
    audio = window_audio(source, take, w, work / "window.wav")
    result = provider.sync_span(SpanRequest(clip, audio, w, w.seconds), work / f"synced-{provider.name}.mp4")
    out = stitch(source, w, result.clip, stitched) if stitched is not None else None
    return w, result, out


# ── choosing one ─────────────────────────────────────────────────────────────

def selected_name() -> str:
    """`AVE_LIPSYNC_PROVIDER`: off (default), fake, sync_so or selfhosted."""
    return (os.environ.get("AVE_LIPSYNC_PROVIDER") or "off").strip().lower()


def providers() -> dict[str, LipSyncProvider]:
    from app.lipsync.fake import FakeLipSyncProvider
    from app.lipsync.selfhosted import SelfHostedLipSyncProvider
    from app.lipsync.vendor import SyncSoLipSyncProvider
    return {p.name: p for p in (FakeLipSyncProvider(), SyncSoLipSyncProvider.from_env(),
                                SelfHostedLipSyncProvider.from_env())}


def status() -> dict:
    """For /health and the review page: what is selected and what each could do."""
    every = providers()
    chosen = selected_name()
    return {
        "selected": chosen if chosen in every and every[chosen].available() else "off",
        "providers": [{"name": n, "available": p.available()} for n, p in every.items()],
    }


def scratch() -> Path:
    return Path(tempfile.mkdtemp(prefix="ave-lipsync-"))
