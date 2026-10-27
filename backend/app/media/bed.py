"""Is there music or noise under the speech? (Run 5, item 8.)

Measured on upload, in well under a second, so the slow part (Demucs, 15c)
runs only for a clip that needs it, and in the background: a replaced line
then keeps the music bed and the room under it.

The measure is the gap between the speech and the quietest tenth of the clip.
A clean recording drops to near silence between words (a gap of 40 dB and
more); a clip with a bed never does. Calibrated on evals/messy: every music and
noise variant measured 10 to 24 dB, the clean, echo, phone, crosstalk and
clipped ones 32 dB and up. Music is told from noise by how tonal the quiet
part is: a few spectral peaks hold nearly all of a music bed's energy.
"""
from __future__ import annotations

import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.media import ffmpeg

RATE = 16000
FRAME = 512                 # 32 ms
BED_GAP_DB = 28.0           # speech less than this above the floor: something plays under it
MUSIC_TONAL = 0.95          # share of the quiet part's energy in its 8 strongest bins
SILENT_DB = -70.0           # a floor under this is silence, whatever the gap


@dataclass(frozen=True)
class Bed:
    kind: str               # "music", "noise" or "none"
    gap_db: float           # speech above the floor
    floor_db: float         # the quietest tenth, dBFS

    @property
    def present(self) -> bool:
        return self.kind != "none"

    def as_dict(self) -> dict:
        return asdict(self)


def measure(x: np.ndarray) -> Bed:
    """The bed under mono samples at RATE."""
    n = len(x) // FRAME
    if n < 10:
        return Bed("none", 0.0, -180.0)
    frames = x[: n * FRAME].reshape(n, FRAME).astype(np.float64)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    speech, floor = float(np.percentile(db, 90)), float(np.percentile(db, 10))
    gap = speech - floor
    if floor < SILENT_DB or gap >= BED_GAP_DB:
        return Bed("none", round(gap, 1), round(floor, 1))
    quiet = frames[db <= np.percentile(db, 25)] * np.hanning(FRAME)
    power = np.abs(np.fft.rfft(quiet, axis=1)) ** 2 + 1e-12
    tonal = float(np.median(np.sort(power, axis=1)[:, -8:].sum(axis=1) / power.sum(axis=1)))
    return Bed("music" if tonal >= MUSIC_TONAL else "noise", round(gap, 1), round(floor, 1))


def detect(media: str | Path) -> Bed | None:
    """The bed under a video's or audio file's sound; None when it cannot be read."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav, _ = ffmpeg.extract_audio(media, Path(tmp) / "bed.wav", sample_rate=RATE)
            with wave.open(str(wav), "rb") as w:
                raw = w.readframes(w.getnframes())
    except Exception:  # noqa: BLE001 - a clip whose sound cannot be read simply has no bed to keep
        return None
    return measure(np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0)
