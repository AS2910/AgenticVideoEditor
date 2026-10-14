"""Where there is a mouth to move (Phase 17b).

A lip-sync model can only re-voice a face that is on screen, and it is billed
by the second. An edit's span is split at the picture's cuts, each shot is
sampled for a face, and only the shots that have one for most of their length
(and are long enough for the vendor to accept) are sent. The rest of the span
keeps its original picture.

Faces are found with OpenCV's YuNet (a 230 KB model vendored under
`app/media/models`); OpenCV is an optional extra (`mouth`), and without it
nothing is a face, so nothing is sent and the picture is left alone.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
SCORE = 0.8             # a detection below this is not a face worth moving a mouth on
SAMPLE_EVERY = 0.25     # seconds between sampled frames in a shot
MAX_SAMPLES = 12        # per shot: enough to know, cheap to take
MIN_SHARE = 0.6         # a face in at least this share of the samples
MIN_SECONDS = 0.4       # shorter than this the vendor refuses the clip
# A face half out of the frame, or a speck in the background, has no mouth worth
# moving (found on the first live spike: a face cut by the frame edge was
# "detected" and the vendor could do nothing with it).
MIN_HEIGHT = 0.10       # of the frame's height
EDGE = 0.01             # a face must sit this far inside the frame, as a share of it

# (frame as a BGR array) -> how many faces. Injectable, so tests never load a model.
CountFn = Callable[[object], int]
# (video path, time in seconds) -> a BGR frame, or None when it cannot be read.
ReadFn = Callable[[Path, float], object | None]


@dataclass(frozen=True)
class Stretch:
    """A run of one shot with a face in it: a mouth to move."""
    start: float
    end: float
    faces: int          # the most faces seen at once; more than one needs a speaker picked

    @property
    def seconds(self) -> float:
        return self.end - self.start


def available() -> bool:
    return importlib.util.find_spec("cv2") is not None and MODEL.is_file()


_detector = None


def _count_faces(frame) -> int:
    """Faces in a frame at the score above, by YuNet (loaded once, resized per frame)."""
    global _detector
    import cv2
    h, w = frame.shape[:2]
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), SCORE, 0.3, 5000)
    _detector.setInputSize((w, h))
    _, found = _detector.detect(frame)
    if found is None:
        return 0
    return sum(1 for fx, fy, fw, fh in found[:, :4] if usable_face(fx, fy, fw, fh, w, h))


def usable_face(x: float, y: float, w: float, h: float, frame_w: int, frame_h: int) -> bool:
    """Whole in the frame (a little inside its edges) and big enough to see a mouth."""
    ex, ey = EDGE * frame_w, EDGE * frame_h
    return (h >= MIN_HEIGHT * frame_h and x >= ex and y >= ey
            and x + w <= frame_w - ex and y + h <= frame_h - ey)


def _read(path: Path, at: float):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at) * 1000)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def sample_times(start: float, end: float) -> list[float]:
    """Times to look at in [start, end): evenly spread, at most MAX_SAMPLES, the
    middle of each slice so a cut at the edge is not sampled."""
    n = max(1, min(MAX_SAMPLES, int((end - start) / SAMPLE_EVERY)))
    step = (end - start) / n
    return [start + step * (i + 0.5) for i in range(n)]


def shots_within(start: float, end: float, cut_times: Sequence[float]) -> list[tuple[float, float]]:
    """[start, end) split at the cuts inside it."""
    edges = [start, *[c for c in sorted(cut_times) if start < c < end], end]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def stretches(
    video: str | Path, start: float, end: float, cut_times: Sequence[float] = (), *,
    count: CountFn | None = None, read: ReadFn | None = None,
) -> list[Stretch]:
    """The parts of [start, end) worth sending to a lip-sync model: one entry
    per shot that has a face for most of it and is long enough. Empty when no
    face finder is available (nothing is sent, the picture is left alone)."""
    if count is None and not available():
        return []
    count, read, video = count or _count_faces, read or _read, Path(video)
    out: list[Stretch] = []
    for a, b in shots_within(start, end, cut_times):
        if b - a < MIN_SECONDS:
            continue
        seen = []
        for t in sample_times(a, b):
            frame = read(video, t)
            seen.append(count(frame) if frame is not None else 0)
        if seen and sum(1 for n in seen if n) / len(seen) >= MIN_SHARE:
            out.append(Stretch(a, b, max(seen)))
    return out
