"""Is the speaker's mouth on screen for this line? (Run 5, item 10.)

A changed line can only be heard without a mismatch when nobody is seen
saying it. So on upload every spoken line gets one of three answers:

- `on_camera`: a face is on screen for most of the line and its mouth moves
  with the line's sound. A new take there will not match the lips (yet).
- `off_camera`: no usable face for most of the line, or a face whose mouth
  stays still while the line is heard (a voice-over over a face). Edited freely.
- `unsure`: anything between (a face some of the time, a mouth that moves but
  not with this sound, the detector unavailable). Treated like on camera in
  the wording, softened ("may be on screen").

How: one decode of the picture at `SAMPLE_FPS`, small (`WIDTH` wide); in
each frame inside a line, YuNet (the face model vendored for Phase 17) finds
the largest usable face and its mouth corners. The mouth patch and an eye
patch are compared with the previous frame: mouth motion over head motion is
the "activity", and its correlation with the change in the line's loudness is
the "sync". Both are cheap (a 60 s clip is a few seconds of CPU) and need no
download; the SyncNet measure (`continuity/lipsync_measure.py`) is the slow,
exact one the quality harness uses.

Everything is injectable (frames, audio, the face finder) so tests never
decode a real face.
"""
from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.media import faces, ffmpeg

log = logging.getLogger(__name__)

ON, OFF, UNSURE = "on_camera", "off_camera", "unsure"
STATES = (ON, OFF, UNSURE)
VERSION = 1

SAMPLE_FPS = 12.5        # a mouth opens and closes 4 to 6 times a second; this sees it
WIDTH = 640              # frames are scaled to this width before the face model sees them
MIN_FACE_HEIGHT = 0.08   # of the frame: smaller than this, nobody reads the lips
FACE_SHARE_ON = 0.5      # a face in at least this share of the line's frames
FACE_SHARE_OFF = 0.2     # ...and under this share, nobody is on screen for it
ACTIVITY_ON = 1.15       # mouth motion this many times the head's: the mouth is talking
ACTIVITY_STILL = 0.9     # at or under this, the mouth is still while the line plays
SYNC_ON = 0.15           # mouth motion correlated with the loudness change at least this much
SYNC_CLEAR = 0.25        # ...or this much, when the mouth moves about as much as the head
# Tuned on VGG's SyncNet sample (a real talking head): its own sound reads
# sync 0.16 to 0.45, unrelated speech under the same face 0.04 to 0.15, a
# still frame under the same speech activity 0.18 to 0.25.
MAX_LAG = 2              # frames each way the correlation may slide (lip-sync is rarely exact)
MIN_PAIRS = 6            # face-to-face frame pairs needed to judge a mouth at all

# (frame BGR) -> the largest usable face as (x, y, w, h, mouth_right_x, mouth_right_y,
# mouth_left_x, mouth_left_y, eye_right_x, eye_right_y, eye_left_x, eye_left_y), or None.
FindFn = Callable[[np.ndarray], tuple[float, ...] | None]


@dataclass(frozen=True)
class LineSpan:
    start: float
    end: float


@dataclass(frozen=True)
class LineVerdict:
    start: float
    end: float
    state: str
    face_share: float          # share of the line's frames with a usable face
    activity: float | None     # mouth motion over head motion; None when not judged
    sync: float | None         # correlation of mouth motion with the loudness change
    why: str                   # one plain sentence, for the admin view and the logs

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def available() -> bool:
    return faces.available()


# ── the face finder ──────────────────────────────────────────────────────────

_detector = None
_detector_size: tuple[int, int] | None = None


def find_face(frame: np.ndarray) -> tuple[float, ...] | None:
    """The largest face YuNet finds that is whole in the frame and big enough to
    read lips on, with its landmarks; None when there is none."""
    global _detector, _detector_size
    import cv2
    h, w = frame.shape[:2]
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(str(faces.MODEL), "", (w, h), faces.SCORE, 0.3, 5000)
    if _detector_size != (w, h):
        _detector.setInputSize((w, h))
        _detector_size = (w, h)
    _, found = _detector.detect(frame)
    if found is None:
        return None
    usable = [f for f in found if f[3] >= MIN_FACE_HEIGHT * h
              and f[0] >= 0 and f[1] >= 0 and f[0] + f[2] <= w and f[1] + f[3] <= h]
    if not usable:
        return None
    f = max(usable, key=lambda r: r[2] * r[3])
    # YuNet: x, y, w, h, right eye, left eye, nose, right mouth corner, left mouth corner, score
    return (float(f[0]), float(f[1]), float(f[2]), float(f[3]),
            float(f[10]), float(f[11]), float(f[12]), float(f[13]),
            float(f[4]), float(f[5]), float(f[6]), float(f[7]))


# ── frames and sound ─────────────────────────────────────────────────────────

def read_frames(video: Path, fps: float = SAMPLE_FPS, width: int = WIDTH) -> Iterator[tuple[float, np.ndarray]]:
    """(time, BGR frame) at `fps`, scaled to `width`, decoded once and streamed."""
    info = next(s for s in ffmpeg.probe(video)["streams"] if s.get("codec_type") == "video")
    w0, h0 = int(info["width"]), int(info["height"])
    w = min(width, w0) // 2 * 2
    h = max(2, round(h0 * w / w0) // 2 * 2)
    proc = subprocess.Popen(
        [ffmpeg.FFMPEG, "-loglevel", "error", "-i", str(video), "-an",
         "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        i = 0
        while True:
            raw = proc.stdout.read(w * h * 3)
            if len(raw) < w * h * 3:
                return
            yield i / fps, np.frombuffer(raw, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def loudness(video: Path, fps: float = SAMPLE_FPS) -> np.ndarray:
    """The soundtrack's level per picture frame (RMS in dB over 1/fps), or an
    empty array when the file has no sound."""
    from app.continuity import signals
    try:
        x = signals.load(video)
    except Exception:  # noqa: BLE001 - no audio stream: nothing to correlate with
        return np.zeros(0)
    hop = int(signals.RATE / fps)
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-5))


# ── per frame ────────────────────────────────────────────────────────────────

def _patch(gray: np.ndarray, cx: float, cy: float, half_w: float, half_h: float) -> np.ndarray | None:
    import cv2
    x0, x1 = int(round(cx - half_w)), int(round(cx + half_w))
    y0, y1 = int(round(cy - half_h)), int(round(cy + half_h))
    if x0 < 0 or y0 < 0 or x1 > gray.shape[1] or y1 > gray.shape[0] or x1 - x0 < 4 or y1 - y0 < 4:
        return None
    p = cv2.resize(gray[y0:y1, x0:x1], (32, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    return (p - p.mean()) / (p.std() + 1e-3)


def patches(frame: np.ndarray, face: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray] | None:
    """The mouth patch and the eye patch of `face`, normalised, or None when
    either runs off the frame."""
    import cv2
    _, _, fw, fh, mrx, mry, mlx, mly, erx, ery, elx, ely = face
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mouth = _patch(gray, (mrx + mlx) / 2, (mry + mly) / 2 + 0.04 * fh, 0.28 * fw, 0.14 * fh)
    eyes = _patch(gray, (erx + elx) / 2, (ery + ely) / 2, 0.38 * fw, 0.12 * fh)
    if mouth is None or eyes is None:
        return None
    return mouth, eyes


# ── per line ─────────────────────────────────────────────────────────────────

def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def best_corr(motion: np.ndarray, level_change: np.ndarray, max_lag: int = MAX_LAG) -> float:
    """The highest correlation of the two series over a small slide either way."""
    best = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = motion[lag:], level_change[: len(level_change) - lag]
        else:
            a, b = motion[:lag], level_change[-lag:]
        n = min(len(a), len(b))
        best = max(best, _corr(a[:n], b[:n]))
    return best


def judge(span: LineSpan, frames: int, with_face: int, mouth: Sequence[float], head: Sequence[float],
          level_change: Sequence[float]) -> LineVerdict:
    """The verdict for one line from what was seen in it: how many frames, how
    many with a face, and per face-to-face pair the mouth's and head's motion and
    the sound's change in level."""
    share = with_face / frames if frames else 0.0
    if frames == 0:
        return LineVerdict(span.start, span.end, UNSURE, 0.0, None, None, "Too short to look at.")
    if share < FACE_SHARE_OFF:
        return LineVerdict(span.start, span.end, OFF, share, None, None, "No face on screen for this line.")
    if len(mouth) < MIN_PAIRS:
        return LineVerdict(span.start, span.end, UNSURE, share, None, None, "A face is on screen, too briefly to read its mouth.")
    m, hd, lc = np.asarray(mouth), np.asarray(head), np.asarray(level_change)
    activity = float(np.median(m) / max(float(np.median(hd)), 1e-3))
    sync = best_corr(m, lc)
    talking = (activity >= ACTIVITY_ON and sync >= SYNC_ON) or (activity > ACTIVITY_STILL and sync >= SYNC_CLEAR)
    if share >= FACE_SHARE_ON and talking:
        return LineVerdict(span.start, span.end, ON, share, activity, sync, "A face is on screen and its mouth moves with this line.")
    if share >= FACE_SHARE_ON and activity <= ACTIVITY_STILL:
        return LineVerdict(span.start, span.end, OFF, share, activity, sync, "A face is on screen but its mouth stays still for this line.")
    return LineVerdict(span.start, span.end, UNSURE, share, activity, sync, "A face is on screen, but it is not clear it is saying this line.")


def detect(
    video: str | Path, lines: Sequence[LineSpan], *,
    frames: Iterable[tuple[float, np.ndarray]] | None = None,
    levels: np.ndarray | None = None, find: FindFn | None = None, fps: float = SAMPLE_FPS,
) -> list[LineVerdict]:
    """A verdict per line. Without the face model every line is `unsure` (we
    cannot say nobody is on screen)."""
    if not lines:
        return []
    if find is None and not available():
        return [LineVerdict(s.start, s.end, UNSURE, 0.0, None, None, "The face finder is not installed.") for s in lines]
    video = Path(video)
    find = find or find_face
    frames = frames if frames is not None else read_frames(video, fps)
    levels = levels if levels is not None else loudness(video, fps)
    ordered = sorted(range(len(lines)), key=lambda i: lines[i].start)
    stats = {i: {"frames": 0, "face": 0, "mouth": [], "head": [], "level": []} for i in range(len(lines))}
    last_end = max(s.end for s in lines)
    prev: tuple[int, int, np.ndarray, np.ndarray] | None = None   # (frame index, line, mouth, eyes)
    for k, (t, frame) in enumerate(frames):
        if t > last_end:
            break
        line = next((i for i in ordered if lines[i].start <= t < lines[i].end), None)
        if line is None:
            prev = None
            continue
        st = stats[line]
        st["frames"] += 1
        face = find(frame)
        got = patches(frame, face) if face is not None else None
        if got is None:
            prev = None
            continue
        st["face"] += 1
        mouth, eyes = got
        if prev is not None and prev[0] == k - 1 and prev[1] == line:
            st["mouth"].append(float(np.mean(np.abs(mouth - prev[2]))))
            st["head"].append(float(np.mean(np.abs(eyes - prev[3]))))
            here = levels[k] if k < len(levels) else -100.0
            before = levels[k - 1] if 0 < k <= len(levels) else -100.0
            st["level"].append(float(abs(here - before)))
        prev = (k, line, mouth, eyes)
    return [judge(lines[i], stats[i]["frames"], stats[i]["face"], stats[i]["mouth"], stats[i]["head"], stats[i]["level"])
            for i in range(len(lines))]


def run(video: str | Path, lines: Sequence[LineSpan]) -> dict:
    """The stored record: per line its verdict, plus how long it took."""
    began = time.monotonic()
    try:
        verdicts = detect(video, lines)
        status = "done"
    except Exception as exc:  # noqa: BLE001 - a crash leaves every line unsure, never a failed upload
        log.warning("on-camera detection failed for %s: %s", video, exc)
        verdicts = [LineVerdict(s.start, s.end, UNSURE, 0.0, None, None, "The picture could not be read.") for s in lines]
        status = "failed"
    return {"version": VERSION, "status": status, "seconds": round(time.monotonic() - began, 2),
            "lines": [v.to_dict() for v in verdicts]}


def state_for(record: dict | None, start: float, end: float) -> str | None:
    """The stored state of the line covering most of [start, end), or None when
    nothing was detected (still running, an old video)."""
    if not record or record.get("status") not in ("done", "failed"):
        return None
    best, overlap = None, 0.0
    for ln in record.get("lines") or []:
        o = min(end, ln["end"]) - max(start, ln["start"])
        if o > overlap:
            best, overlap = ln["state"], o
    return best
