"""Measured lip-sync of a take (Phase 17d), optional extra `mouth`.

SyncNet (Chung & Zisserman) embeds 0.2 s of mouth pictures and 0.2 s of speech
into one space; how far apart the two land, over a few frames of offset, says
whether the lips are saying what the audio says:
- **LSE-D** is the smallest mean distance over offsets of -15..+15 frames. Lower
  is better synced.
- **LSE-C** is the median distance minus that smallest one: how sharply the best
  offset stands out. Higher is better.

The score is relative: the original footage has its own LSE-D (a dubbed or
badly-lit shot never reads 0), and an edit passes when it lands within
`PASS_WITHIN` of it. Nothing here may break the pipeline: without torch/OpenCV,
without the weights (offline), without a face, or on a stretch too short to
judge, the score is None and the take is not blocked. The model loads on first
use and stays loaded; `embed` is injectable so tests never load it.

The network is written out here to match the published `syncnet_v2.model`
checkpoint (VGG, Oxford); the weights are downloaded once into the cache dir.
"""
from __future__ import annotations

import logging
import os
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.continuity import signals
from app.media import ffmpeg

log = logging.getLogger(__name__)

WEIGHTS_URLS = (
    "http://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model",
)
WEIGHTS_NAME = "syncnet_v2.model"
DETECTOR = Path(__file__).resolve().parents[1] / "media" / "models" / "face_detection_yunet_2023mar.onnx"
FACE_SCORE = 0.8

FPS = 25                  # SyncNet's clock: 25 pictures and 100 MFCC frames a second
FACE_SIZE = 224           # the face crop the video stream takes (the checkpoint's first
                          # conv is 3-channel and ends in a 6x6 kernel only 224 reaches)
WINDOW = 5                # pictures per embedding (0.2 s); 20 MFCC frames go with them
MAX_SHIFT = 15            # offsets tried each way, in pictures
MIN_SECONDS = 0.6         # less than this much face carries no judgeable sync
CROP_MARGIN = 0.4         # the reference's `cs`: room around the face box, mostly below
MAX_GAP = 5               # frames without a detection bridged by interpolation
PASS_WITHIN = 1.0         # the roadmap's exit: edited LSE-D within this of the original's
FAIL_BEYOND = 4.0         # ...and the score reaches 0 this far above it

# (frames BGR uint8 (T, 224, 224, 3), mfcc (13, 4T)) -> (video feats, audio feats), each (N, 1024)
Embed = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]

_model = None
_failed = False     # a model that could not load is not retried every take


@dataclass(frozen=True)
class LseScore:
    distance: float       # LSE-D, lower is better
    confidence: float     # LSE-C, higher is better
    offset_frames: int    # the audio's best offset against the picture; 0 = in sync


def available() -> bool:
    """Whether the `mouth` extra can run: importable, and not switched off
    with AVE_MOUTH_MEASURE=0."""
    if os.environ.get("AVE_MOUTH_MEASURE") == "0":
        return False
    try:
        import cv2  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def lip_sync_score(edited: LseScore | None, original: LseScore | None) -> float | None:
    """0-1: 1 when the edit's LSE-D is no worse than the original footage's own,
    falling linearly to 0 at `FAIL_BEYOND` above it."""
    if edited is None or original is None:
        return None
    worse = edited.distance - original.distance
    return max(0.0, min(1.0, 1.0 - worse / FAIL_BEYOND))


# --- the network -------------------------------------------------------------

def _build():
    """The SyncNet v2 two-stream network, layer-for-layer as the checkpoint has it."""
    from torch import nn

    def bn2(c):
        return nn.BatchNorm2d(c, momentum=0.1, eps=1e-5)

    def bn3(c):
        return nn.BatchNorm3d(c, momentum=0.1, eps=1e-5)

    class SyncNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.netcnnaud = nn.Sequential(
                nn.Conv2d(1, 64, 3, 1, 1), bn2(64), nn.ReLU(inplace=True),
                nn.MaxPool2d(1, 1),
                nn.Conv2d(64, 192, 3, 1, 1), bn2(192), nn.ReLU(inplace=True),
                nn.MaxPool2d(3, (1, 2)),
                nn.Conv2d(192, 384, 3, 1, 1), bn2(384), nn.ReLU(inplace=True),
                nn.Conv2d(384, 256, 3, 1, 1), bn2(256), nn.ReLU(inplace=True),
                nn.Conv2d(256, 256, 3, 1, 1), bn2(256), nn.ReLU(inplace=True),
                nn.MaxPool2d(3, 2),
                nn.Conv2d(256, 512, (5, 4)), bn2(512), nn.ReLU(inplace=True),
            )
            self.netfcaud = nn.Sequential(
                nn.Linear(512, 512), nn.BatchNorm1d(512), nn.ReLU(), nn.Linear(512, 1024),
            )
            self.netfclip = nn.Sequential(
                nn.Linear(512, 512), nn.BatchNorm1d(512), nn.ReLU(), nn.Linear(512, 1024),
            )
            self.netcnnlip = nn.Sequential(
                nn.Conv3d(3, 96, (5, 7, 7), (1, 2, 2), 0), bn3(96), nn.ReLU(inplace=True),
                nn.MaxPool3d((1, 3, 3), (1, 2, 2)),
                nn.Conv3d(96, 256, (1, 5, 5), (1, 2, 2), (0, 1, 1)), bn3(256), nn.ReLU(inplace=True),
                nn.MaxPool3d((1, 3, 3), (1, 2, 2), (0, 1, 1)),
                nn.Conv3d(256, 256, (1, 3, 3), 1, (0, 1, 1)), bn3(256), nn.ReLU(inplace=True),
                nn.Conv3d(256, 256, (1, 3, 3), 1, (0, 1, 1)), bn3(256), nn.ReLU(inplace=True),
                nn.Conv3d(256, 256, (1, 3, 3), 1, (0, 1, 1)), bn3(256), nn.ReLU(inplace=True),
                nn.MaxPool3d((1, 3, 3), (1, 2, 2)),
                nn.Conv3d(256, 512, (1, 6, 6)), bn3(512), nn.ReLU(inplace=True),
            )

        def audio(self, x):
            return self.netfcaud(self.netcnnaud(x).flatten(1))

        def video(self, x):
            return self.netfclip(self.netcnnlip(x).flatten(1))

    return SyncNet()


def _cache_dir() -> Path:
    return Path(os.environ.get("AVE_MODEL_CACHE") or Path.home() / ".cache" / "voltage") / "syncnet"


def _weights() -> Path:
    """The checkpoint on disk, fetched once from the first source that answers."""
    path = _cache_dir() / WEIGHTS_NAME
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for url in WEIGHTS_URLS:
        part = path.with_suffix(".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as src, open(part, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            part.replace(path)
            return path
        except Exception as exc:  # noqa: BLE001
            last = exc
            part.unlink(missing_ok=True)
    raise RuntimeError(f"could not download {WEIGHTS_NAME}: {last}")


def _load_embedder() -> Embed | None:
    global _model, _failed
    if _model is None and not _failed:
        try:
            import torch

            net = _build()
            try:
                net.load_state_dict(torch.load(_weights(), map_location="cpu"))
            except Exception:
                (_cache_dir() / WEIGHTS_NAME).unlink(missing_ok=True)   # a torn download is not kept
                raise
            _model = net.eval()
        except Exception as exc:  # noqa: BLE001  # offline, no disk, no extra: unmeasured, not broken
            log.warning("lip-sync model unavailable: %s", exc)
            _failed = True
    if _model is None:
        return None
    net = _model

    def embed(frames: np.ndarray, mfcc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import torch

        n = min(len(frames), mfcc.shape[1] // 4) - WINDOW + 1
        if n < 1:
            return np.zeros((0, 1024), np.float32), np.zeros((0, 1024), np.float32)
        # (T, H, W, 3) BGR 0-255 (the net takes raw pixels) -> (3, T, H, W), and 5-picture windows one picture apart
        clip = torch.from_numpy(frames[: n + WINDOW - 1]).permute(3, 0, 1, 2).float()
        cc = torch.from_numpy(mfcc).float()
        video, audio = [], []
        with torch.no_grad():
            for lo in range(0, n, 32):
                hi = min(n, lo + 32)
                video.append(net.video(torch.stack([clip[:, i:i + WINDOW] for i in range(lo, hi)])))
                audio.append(net.audio(torch.stack([cc[None, :, i * 4:i * 4 + 20] for i in range(lo, hi)])))
        return torch.cat(video).numpy(), torch.cat(audio).numpy()

    return embed


# --- audio: MFCC the way the reference computes it -----------------------------

def _mel_filters(n_filters: int = 26, nfft: int = 512, rate: int = signals.RATE) -> np.ndarray:
    def mel(hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    bins = np.floor((nfft + 1) * hz(np.linspace(mel(0.0), mel(rate / 2), n_filters + 2)) / rate).astype(int)
    bank = np.zeros((n_filters, nfft // 2 + 1))
    for j in range(n_filters):
        for i in range(bins[j], bins[j + 1]):
            bank[j, i] = (i - bins[j]) / (bins[j + 1] - bins[j])
        for i in range(bins[j + 1], bins[j + 2]):
            bank[j, i] = (bins[j + 2] - i) / (bins[j + 2] - bins[j + 1])
    return bank


def _dct(n: int, keep: int) -> np.ndarray:
    """The first `keep` columns of the orthonormal type-II DCT matrix (no scipy)."""
    basis = np.cos(np.pi * (np.arange(n)[:, None] + 0.5) * np.arange(keep)[None, :] / n)
    basis *= np.sqrt(2.0 / n)
    basis[:, 0] /= np.sqrt(2.0)
    return basis


def mfcc(x: np.ndarray, rate: int = signals.RATE) -> np.ndarray:
    """13 cepstral coefficients, 25 ms windows every 10 ms: (13, frames). The
    same recipe as python_speech_features' defaults, which SyncNet was trained on
    (pre-emphasis 0.97, 26 mel filters, lifter 22, log-energy in coefficient 0).
    `x` is float in [-1, 1]; it is scaled to 16-bit range first, because the net
    was trained on raw WAV integers and coefficient 0 is an absolute level."""
    x = x.astype(np.float64) * 32768.0
    x = np.append(x[:1], x[1:] - 0.97 * x[:-1])
    size, step = int(0.025 * rate), int(0.010 * rate)
    count = 1 if len(x) <= size else 1 + int(np.ceil((len(x) - size) / step))
    padded = np.zeros((count - 1) * step + size)
    padded[: len(x)] = x
    index = np.arange(size)[None, :] + step * np.arange(count)[:, None]
    power = np.abs(np.fft.rfft(padded[index], 512)) ** 2 / 512
    energy = power.sum(axis=1)
    energy[energy == 0] = np.finfo(float).eps
    mel = power @ _mel_filters(rate=rate).T
    mel[mel == 0] = np.finfo(float).eps
    ceps = np.log(mel) @ _dct(mel.shape[1], 13)
    ceps *= 1 + (22 / 2.0) * np.sin(np.pi * np.arange(13) / 22)
    ceps[:, 0] = np.log(energy)
    return ceps.T.astype(np.float32)


# --- picture: the main face, tracked -------------------------------------------

def _detect(frame: np.ndarray, detector) -> tuple[float, float, float] | None:
    """The largest face in a BGR frame as (centre x, centre y, half size), or None."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
    return float(x + fw / 2), float(y + fh / 2), float(max(fw, fh) / 2)


def track(boxes: list[tuple[float, float, float] | None]) -> list[tuple[int, list[tuple[float, float, float]]]]:
    """Runs of consecutive pictures with a face: [(first index, boxes)]. Gaps of
    up to MAX_GAP are bridged by interpolation; a longer gap, or a jump of more
    than a face (a cut), starts a new run. Boxes are smoothed with a median over
    5 pictures so the crop does not shake. Runs under MIN_SECONDS are dropped."""
    runs: list[list[int]] = []
    for i, box in enumerate(boxes):
        if box is None:
            continue
        if runs:
            last = runs[-1][-1]
            px, py, ps = boxes[last]
            near = abs(box[0] - px) + abs(box[1] - py) <= 2 * max(ps, box[2])
            if i - last - 1 <= MAX_GAP and near:
                runs[-1].append(i)
                continue
        runs.append([i])
    out = []
    for run in runs:
        first, last = run[0], run[-1]
        if (last - first + 1) < MIN_SECONDS * FPS:
            continue
        have = np.array([boxes[i] for i in run], dtype=float)
        full = np.stack([np.interp(np.arange(first, last + 1), run, have[:, k]) for k in range(3)], axis=1)
        pad = np.pad(full, ((2, 2), (0, 0)), mode="edge")
        smooth = np.median(np.stack([pad[k:k + len(full)] for k in range(5)]), axis=0)
        out.append((first, [tuple(map(float, row)) for row in smooth]))
    return out


def crop(frame: np.ndarray, box: tuple[float, float, float]) -> np.ndarray:
    """The 224x224 face crop SyncNet expects: the face box with CROP_MARGIN of
    room, shifted down so the mouth and chin sit well inside it (the reference's
    framing), edge-padded where it runs off the picture."""
    import cv2

    cx, cy, s = box
    s = max(s, 8.0)
    x0, x1 = round(cx - s * (1 + CROP_MARGIN)), round(cx + s * (1 + CROP_MARGIN))
    y0, y1 = round(cy - s), round(cy + s * (1 + 2 * CROP_MARGIN))
    pad = int(s * (1 + 2 * CROP_MARGIN)) + 1
    padded = cv2.copyMakeBorder(frame, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(110, 110, 110))
    face = padded[y0 + pad:y1 + pad, x0 + pad:x1 + pad]
    return cv2.resize(face, (FACE_SIZE, FACE_SIZE), interpolation=cv2.INTER_AREA)


def _read_frames(video: Path):
    """BGR frames at 25 fps, one at a time, so a long file never sits in memory."""
    info = next(s for s in ffmpeg.probe(video)["streams"] if s.get("codec_type") == "video")
    w, h = int(info["width"]), int(info["height"])
    proc = subprocess.Popen(
        [ffmpeg.FFMPEG, "-loglevel", "error", "-i", str(video), "-an", "-vf", f"fps={FPS}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        while True:
            raw = proc.stdout.read(w * h * 3)
            if len(raw) < w * h * 3:
                return
            yield np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def face_runs(video: Path) -> list[tuple[int, np.ndarray]]:
    """[(first picture index, crops (T, 224, 224, 3))] for each stretch with a main face."""
    import cv2

    detector = cv2.FaceDetectorYN.create(str(DETECTOR), "", (320, 320), FACE_SCORE)
    # Two passes: the boxes of a run are only final (bridged, smoothed) once all
    # of it is seen, so detect first, then decode again to cut the crops.
    boxes = [_detect(frame, detector) for frame in _read_frames(video)]
    runs = track(boxes)
    if not runs:
        return []
    wanted = {i: box for first, bs in runs for i, box in enumerate(bs, first)}
    crops: dict[int, np.ndarray] = {}
    for i, frame in enumerate(_read_frames(video)):
        if i in wanted:
            crops[i] = crop(frame, wanted[i])
    return [(first, np.stack([crops[i] for i in range(first, first + len(bs))])) for first, bs in runs]


# --- the measurement ---------------------------------------------------------

def distances(video_feats: np.ndarray, audio_feats: np.ndarray) -> np.ndarray:
    """(N, 2 * MAX_SHIFT + 1): each picture's embedding against the audio's at every
    offset. Audio rows past either end are zero vectors, as in the reference."""
    padded = np.pad(audio_feats, ((MAX_SHIFT, MAX_SHIFT), (0, 0)))
    width = 2 * MAX_SHIFT + 1
    return np.stack([
        np.linalg.norm(video_feats[i][None, :] - padded[i:i + width] + 1e-6, axis=1)
        for i in range(len(video_feats))
    ])


def score(dists: np.ndarray) -> LseScore:
    """LSE-D / LSE-C and the best offset from per-picture distance curves."""
    curve = dists.mean(axis=0)
    best = int(np.argmin(curve))
    return LseScore(
        distance=float(curve[best]),
        confidence=float(np.median(curve) - curve[best]),
        offset_frames=MAX_SHIFT - best,
    )


def lse(video: Path, audio: Path | None = None, *, embed: Embed | None = None) -> LseScore | None:
    """LSE-D / LSE-C of `video`'s main face against `audio` (default: its own
    soundtrack). None when it cannot be judged: no extra, no model, no face for
    MIN_SECONDS, or any failure."""
    try:
        if embed is None:
            if not available():
                return None
            embed = _load_embedder()
            if embed is None:
                return None
        runs = face_runs(Path(video))
        if not runs:
            return None
        samples = signals.load(audio or video)
        per_frame = signals.RATE // FPS
        curves = []
        for first, crops in runs:
            clip = samples[first * per_frame:(first + len(crops)) * per_frame]
            if clip.size < MIN_SECONDS * signals.RATE:
                continue
            v, a = embed(crops, mfcc(clip))
            if len(v):
                curves.append(distances(np.asarray(v, np.float64), np.asarray(a, np.float64)))
        if not curves:
            return None
        return score(np.concatenate(curves))
    except Exception as exc:  # noqa: BLE001
        log.warning("lip-sync measure failed: %s", exc)
        return None
