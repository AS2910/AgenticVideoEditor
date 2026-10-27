"""The lip-sync quality harness (Run 5, item 10): a confidence score per clip.

A score says how sure we are that the mouth on screen is saying the sound
under it, 0 to 1. Two ways to read it, best first:

- `syncnet`: SyncNet's LSE-C (`continuity/lipsync_measure.py`, needs torch
  and a 55 MB download, about 15 s on CPU for 13 s of video). Synced footage
  reads 7 to 10, a 1 s shift about 2; the score is LSE-C / 8, capped at 1.
- `motion`: the cheap read the on-camera detector uses (mouth motion against
  the change in loudness). Coarse, but always there.

A provider's result is judged against the original window's own score, never
an absolute bar: dubbed or generated footage never reads as perfectly synced,
so "as good as the original" is the honest pass. `compare` gives both scores
and a verdict for the review page.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from app.lipsync import on_camera

SYNCNET_FULL = 8.0        # LSE-C at which the score reads 1.0
MOTION_FULL = 0.5         # motion correlation at which the score reads 1.0
PASS_SHARE = 0.8          # a result passes at this share of the original's own score
TRUST_SYNCNET = 4.0       # an original under this LSE-C has no sync to compare with (Phase 17)


@dataclass(frozen=True)
class Confidence:
    score: float | None       # 0..1; None when there is no face to judge
    method: str               # "syncnet" | "motion" | "none"
    detail: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _syncnet_on() -> bool:
    if os.environ.get("AVE_MOUTH_MEASURE") == "0":
        return False
    from app.continuity import lipsync_measure
    return lipsync_measure.available()


def confidence(video: str | Path, audio: str | Path | None = None, *, method: str | None = None) -> Confidence:
    """How sure we are the face in `video` is saying `audio` (default: its own sound)."""
    method = method or ("syncnet" if _syncnet_on() else "motion")
    if method == "syncnet":
        from app.continuity import lipsync_measure
        found = lipsync_measure.lse(Path(video), Path(audio) if audio else None)
        if found is not None:
            return Confidence(round(min(1.0, max(0.0, found.confidence / SYNCNET_FULL)), 3), "syncnet",
                              {"lse_d": round(found.distance, 3), "lse_c": round(found.confidence, 3),
                               "offset_frames": found.offset_frames})
    return _motion(Path(video), Path(audio) if audio else None)


def _motion(video: Path, audio: Path | None) -> Confidence:
    from app.media import ffmpeg
    duration = ffmpeg.duration_of(video)
    levels = on_camera.loudness(audio or video)
    verdict = on_camera.detect(video, [on_camera.LineSpan(0.0, duration)], levels=levels)[0]
    if verdict.sync is None or verdict.face_share < on_camera.FACE_SHARE_ON:
        return Confidence(None, "none", {"face_share": round(verdict.face_share, 3), "why": verdict.why})
    score = max(0.0, min(1.0, verdict.sync / MOTION_FULL))
    return Confidence(round(score, 3), "motion", verdict.to_dict())


def compare(original: Confidence, result: Confidence) -> dict:
    """The review page's verdict: the result against the original's own score."""
    if result.score is None:
        return {"verdict": "no_face", "say": "No face to judge in the result."}
    if original.score is None or (original.method == "syncnet" and original.detail.get("lse_c", 0) < TRUST_SYNCNET):
        return {"verdict": "no_baseline", "say": "The original has no clear lip-sync to compare with."}
    ok = result.score >= PASS_SHARE * original.score
    return {"verdict": "pass" if ok else "below",
            "say": "As well synced as the original." if ok else "Less well synced than the original."}
