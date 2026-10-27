"""The fake lip-sync provider: free, instant, for tests and the review page.

It does not move a mouth. It returns the window it was sent, the same length
and frame rate, with the new audio on it and a thin bar along the bottom over
the changed span, so a stitch-back is easy to see and to check frame by frame.
"""
from __future__ import annotations

from pathlib import Path

from app.lipsync.provider import SpanRequest, SpanResult
from app.media import ffmpeg


class FakeLipSyncProvider:
    name = "fake"

    def available(self) -> bool:
        return True

    def usd_for(self, seconds: float) -> float:
        return 0.0

    def sync_span(self, request: SpanRequest, dest: Path) -> SpanResult:
        w = request.window
        lo, hi = w.lead, w.lead + (w.end - w.start)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", "-i", str(request.clip), "-i", str(request.audio),
            "-vf", f"drawbox=x=0:y=ih-ih/40:w=iw:h=ih/40:color=0x7CFC00:t=fill:enable='between(t,{lo:.3f},{hi:.3f})'",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(dest),
        ])
        return SpanResult(dest, self.name, 0.0, ("The fake provider marks the span; it does not move the mouth.",))
