"""What the clip is made of, from its signals (2026-10-20): the beats, the
energy, what sound is already there, and which frames are worth a look.

No model here; the first-look call (adapters.claude_planner.understand) is
given these and adds what only the picture can tell (the genre, the
subjects, visual events such as "knockdown 0:13"). Everything carries a
time and a confidence:

- cuts from ffmpeg's scene score (`media.shots`);
- motion peaks from the frame-difference curve (`media.motion`);
- audio events where the momentary loudness jumps, each named by a small
  classifier from its spectrum and rhythm: crowd roar, music, speech,
  laughter, a bell, a hit;
- an energy curve, motion and loudness together, 0 to 1 every half second;
- what audio runs under the clip (speech, music, crowd);
- adaptive frame times: every cut, every motion or audio peak, plus one a
  second, up to about 24.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app.media import loudness as L

HOP = 0.1            # seconds between loudness readings
WINDOW = 0.4         # momentary loudness window
ENERGY_STEP = 0.5
MAX_FRAMES = 24
MIN_GAP = 0.4        # frames closer than this are one
LOUD_JUMP_DB = 6.0   # an audio event: this much over the last two seconds
QUIET = -45.0        # nothing below this is an event


@dataclass(frozen=True)
class Beat:
    at: float
    kind: str            # cut | motion | audio | visual
    label: str           # "cut", "motion peak", "crowd roar", "knockdown"
    confidence: float    # 0 to 1
    source: str = "signal"   # signal | vision | user

    def as_dict(self) -> dict:
        return {**asdict(self), "at": round(self.at, 2), "confidence": round(self.confidence, 2)}


@dataclass
class Signals:
    duration: float
    width: int = 0
    height: int = 0
    beats: list[Beat] = field(default_factory=list)
    energy: list[float] = field(default_factory=list)       # 0..1 every ENERGY_STEP seconds
    audio: dict = field(default_factory=dict)               # {"speech": share, "music": share, "crowd": share, "silence": share}
    frame_times: list[float] = field(default_factory=list)

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        return "vertical" if self.height > self.width * 1.1 else "square" if self.height > self.width * 0.9 else "landscape"

    def as_dict(self) -> dict:
        return {"duration": round(self.duration, 3), "width": self.width, "height": self.height,
                "orientation": self.orientation, "beats": [b.as_dict() for b in self.beats],
                "energy": [round(e, 2) for e in self.energy], "energy_step": ENERGY_STEP,
                "audio": {k: round(v, 2) for k, v in self.audio.items()},
                "frame_times": [round(t, 2) for t in self.frame_times]}


# ── sound ─────────────────────────────────────────────────────────────────────

def loudness_curve(x: np.ndarray, rate: int = L.RATE) -> np.ndarray:
    """Momentary loudness (LUFS, 400 ms) every 100 ms."""
    y = L.k_weighted(x, rate)
    power = (y ** 2).sum(axis=1)
    win, hop = int(WINDOW * rate), int(HOP * rate)
    if len(power) < win:
        return np.array([L._lufs(power.mean())]) if len(power) else np.zeros(0)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, len(power) - win + 1, hop)
    return L._lufs((csum[starts + win] - csum[starts]) / win)


def _features(seg: np.ndarray, rate: int) -> dict:
    """Spectral flatness, centroid, harmonicity and the 2 to 10 Hz rhythm of the envelope."""
    mono = seg.mean(axis=1) if seg.ndim == 2 else seg
    mono = mono - mono.mean()
    if len(mono) < rate // 10 or not np.any(mono):
        return {"flat": 1.0, "centroid": 0.0, "harmonic": 0.0, "rhythm": 0.0, "decay": 0.0, "length": len(mono) / rate}
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) + 1e-12
    freqs = np.fft.rfftfreq(len(mono), 1 / rate)
    band = (freqs > 80) & (freqs < 8000)
    s = spec[band]
    flat = float(np.exp(np.mean(np.log(s))) / np.mean(s))
    centroid = float((freqs[band] * s).sum() / s.sum())
    # Harmonicity: the strongest autocorrelation in a 60 to 1000 Hz pitch range.
    n = min(len(mono), rate // 2)
    seg_ac = mono[:n]
    ac = np.fft.irfft(np.abs(np.fft.rfft(seg_ac, 2 * n)) ** 2)[:n]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = rate // 1000, rate // 60
    harmonic = float(ac[lo:hi].max()) if hi < len(ac) else 0.0
    # Envelope rhythm: how much of the envelope's motion is at syllable rates (3 to 8 Hz).
    frame = rate // 100
    m = len(mono) // frame
    env = np.sqrt((mono[: m * frame].reshape(m, frame) ** 2).mean(axis=1)) if m else np.zeros(1)
    rhythm = 0.0
    if m >= 30:
        e = env - env.mean()
        es = np.abs(np.fft.rfft(e)) ** 2
        ef = np.fft.rfftfreq(len(e), 0.01)
        total = es[(ef > 0.5) & (ef < 20)].sum() + 1e-12
        rhythm = float(es[(ef >= 3) & (ef <= 8)].sum() / total)
    decay = float(env[-1] / (env.max() + 1e-12)) if m else 0.0
    return {"flat": flat, "centroid": centroid, "harmonic": harmonic, "rhythm": rhythm, "decay": decay, "length": len(mono) / rate}


def classify(seg: np.ndarray, rate: int = L.RATE) -> tuple[str, float]:
    """A small classifier: what a stretch of sound most likely is, and how sure.
    Rules on a few spectral and rhythmic features, not a learned model; the
    confidence says how clearly the features point one way."""
    f = _features(seg, rate)
    if f["length"] < 0.1:
        return "hit", 0.3
    scores = {
        # Broadband noise that holds: a crowd, applause, a roar.
        "crowd roar": (f["flat"] > 0.25) * 0.5 + (f["harmonic"] < 0.45) * 0.3 + (f["length"] > 0.6) * 0.2,
        # Voiced with a syllable rhythm in the speech band.
        "speech": (f["harmonic"] > 0.3) * 0.35 + (f["rhythm"] > 0.25) * 0.4 + (300 < f["centroid"] < 3000) * 0.25,
        # Tonal and steady.
        "music": (f["harmonic"] > 0.5) * 0.4 + (f["rhythm"] < 0.25) * 0.3 + (f["flat"] < 0.15) * 0.3,
        # Bright, pure and ringing on.
        "bell": (f["harmonic"] > 0.7) * 0.35 + (f["centroid"] > 1500) * 0.35 + (f["decay"] > 0.2) * 0.3,
        # Voiced bursts at a laugh's rate.
        "laughter": (f["harmonic"] > 0.25) * 0.3 + (f["rhythm"] > 0.35) * 0.35 + (f["flat"] > 0.12) * 0.35,
        # Short and sharp.
        "hit": (f["length"] < 0.3) * 0.5 + (f["decay"] < 0.1) * 0.5,
    }
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    confidence = max(0.2, min(0.9, ordered[0] - 0.5 * ordered[1] + 0.3))
    return best, round(confidence, 2)


def audio_events(x: np.ndarray, rate: int = L.RATE) -> list[Beat]:
    """Where the sound jumps: momentary loudness this far over the last two
    seconds, then named by the classifier on the second that follows."""
    curve = loudness_curve(x, rate)
    events: list[Beat] = []
    back = int(2.0 / HOP)
    last = -10.0
    for i in range(len(curve)):
        if curve[i] < QUIET:
            continue
        before = curve[max(0, i - back): i]
        base = float(np.median(before)) if len(before) >= 3 else None
        t = i * HOP + WINDOW / 2
        if base is None or curve[i] - max(base, QUIET - 10) < LOUD_JUMP_DB or t - last < 1.0:
            continue
        seg = x[int(t * rate): int((t + 1.0) * rate)]
        label, conf = classify(seg, rate)
        events.append(Beat(round(t, 2), "audio", label, conf))
        last = t
    return events


def audio_present(x: np.ndarray, rate: int = L.RATE, words: list[tuple[float, float]] | None = None) -> dict:
    """The share of the clip that is speech, music, crowd or quiet, second by second."""
    n = int(len(x) / rate)
    counts = {"speech": 0, "music": 0, "crowd": 0, "silence": 0}
    for k in range(max(1, n)):
        seg = x[k * rate:(k + 1) * rate]
        if not len(seg) or L.loudness(seg, rate) < QUIET:
            counts["silence"] += 1
            continue
        if words and any(a < k + 1 and k < b for a, b in words):
            counts["speech"] += 1
            continue
        label, _ = classify(seg, rate)
        counts["crowd" if label in ("crowd roar", "laughter") else "music" if label in ("music", "bell") else "speech" if label == "speech" else "crowd"] += 1
    total = max(1, sum(counts.values()))
    return {k: v / total for k, v in counts.items()}


# ── picture ───────────────────────────────────────────────────────────────────

def motion_peaks(curve: list[float], step: float) -> list[Beat]:
    """Local maxima well over the clip's usual motion."""
    c = np.asarray(curve, dtype=float)
    if len(c) < 5 or not np.any(c):
        return []
    mean, sd = c.mean(), c.std()
    out = []
    for i in range(1, len(c) - 1):
        if c[i] >= c[i - 1] and c[i] > c[i + 1] and c[i] > mean + 1.5 * sd:
            conf = float(min(0.9, 0.4 + (c[i] - mean) / (4 * sd + 1e-9)))
            if not out or i * step - out[-1].at >= 1.0:
                out.append(Beat(round((i + 0.5) * step, 2), "motion", "motion peak", round(conf, 2)))
    return out


def energy_curve(motion: list[float], motion_step: float, loud: np.ndarray, duration: float) -> list[float]:
    """Motion and loudness together, 0 to 1, every half second."""
    n = max(1, math.ceil(duration / ENERGY_STEP))
    m = np.asarray(motion, dtype=float)
    out = []
    for k in range(n):
        a, b = k * ENERGY_STEP, (k + 1) * ENERGY_STEP
        mv = m[int(a / motion_step): max(int(a / motion_step) + 1, int(b / motion_step))]
        lv = loud[int(a / HOP): max(int(a / HOP) + 1, int(b / HOP))] if len(loud) else np.array([L.SILENCE])
        out.append((float(mv.mean()) if mv.size else 0.0, float(np.max(lv)) if lv.size else L.SILENCE))
    mot = np.array([o[0] for o in out])
    lou = np.array([max(o[1], -60.0) for o in out])
    norm = lambda v: (v - v.min()) / (v.max() - v.min()) if v.max() > v.min() else np.zeros_like(v)   # noqa: E731
    return [float(x) for x in np.clip(0.5 * norm(mot) + 0.5 * norm(lou), 0, 1)]


def adaptive_frame_times(duration: float, beats: list[Beat], limit: int = MAX_FRAMES) -> list[float]:
    """Every cut (just after it), every peak, then one a second, nearest-first
    merged, up to `limit`."""
    edge = min(0.3, duration / 2)
    must = sorted({min(duration - edge, max(edge, b.at + (0.15 if b.kind == "cut" else 0.0))) for b in beats})
    chosen: list[float] = []
    for t in must:
        if all(abs(t - c) >= MIN_GAP for c in chosen):
            chosen.append(t)
    fill = [edge + k for k in range(int(max(0.0, duration - 2 * edge)) + 1)]
    for t in fill:
        if len(chosen) >= limit:
            break
        if all(abs(t - c) >= MIN_GAP for c in chosen):
            chosen.append(t)
    return sorted(round(t, 2) for t in chosen[:limit])


def merge_beats(*groups: list[Beat]) -> list[Beat]:
    """All beats by time; two of a kind closer than half a second are one (the surer stays)."""
    out: list[Beat] = []
    for b in sorted((b for g in groups for b in g), key=lambda b: (b.at, -b.confidence)):
        twin = next((o for o in out if o.kind == b.kind and abs(o.at - b.at) < 0.5), None)
        if twin is None:
            out.append(b)
        elif b.confidence > twin.confidence:
            out[out.index(twin)] = b
    return out


PROXY_HEIGHT = 360


def proxy(path: str | Path, out_dir: str | Path | None, height: int) -> Path:
    """A small copy of the picture for reading cuts and motion: an 8K phone
    clip decoded twice at full size takes most of a minute; at 360p, seconds.
    Made once and kept beside the video's media."""
    from app.media import ffmpeg
    if out_dir is None or height <= PROXY_HEIGHT * 2:
        return Path(path)
    dest = Path(out_dir) / f"proxy-{PROXY_HEIGHT}.mp4"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part.mp4")
        ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(path), "-an",
                                    "-vf", f"scale=-2:{PROXY_HEIGHT}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", str(tmp)])
        tmp.replace(dest)
    return dest


def read_signals(path: str | Path, duration: float, words: list[tuple[float, float]] | None = None,
                 cache_dir: str | Path | None = None) -> Signals:
    """The clip's signals, from its file (ffmpeg for sound, cuts and motion);
    a large picture is read from a small proxy kept in `cache_dir`."""
    from app.media import ffmpeg, motion, shots
    from app.render.compose import decode
    sig = Signals(duration=duration)
    try:
        for s in ffmpeg.probe(path)["streams"]:
            if s.get("codec_type") == "video":
                w, h = int(s.get("width") or 0), int(s.get("height") or 0)
                rot = abs(int((s.get("tags") or {}).get("rotate") or 0))
                for side in s.get("side_data_list") or []:
                    rot = abs(int(side.get("rotation") or rot))
                sig.width, sig.height = (h, w) if rot in (90, 270) else (w, h)
                break
    except Exception:  # noqa: BLE001 - the shape is a nicety
        pass
    try:
        x = decode(path).astype(np.float64)
    except Exception:  # noqa: BLE001 - a clip without sound
        x = np.zeros((int(duration * L.RATE), 1))
    loud = loudness_curve(x) if len(x) else np.zeros(0)
    try:
        picture = proxy(path, cache_dir, max(sig.width, sig.height) if sig.width else 0)
    except Exception:  # noqa: BLE001 - the original will do, slowly
        picture = Path(path)
    try:
        cut_beats = [Beat(t, "cut", "cut", 0.8) for t in shots.cuts(picture)]
    except Exception:  # noqa: BLE001
        cut_beats = []
    try:
        curve = motion.motion(picture, 0.0, duration)
    except Exception:  # noqa: BLE001
        curve = []
    sig.beats = merge_beats(cut_beats, motion_peaks(curve, motion.CHUNK), audio_events(x) if len(x) else [])
    sig.energy = energy_curve(curve, motion.CHUNK, loud, duration)
    sig.audio = audio_present(x, words=words) if len(x) else {"silence": 1.0}
    sig.frame_times = adaptive_frame_times(duration, sig.beats)
    return sig
