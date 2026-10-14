"""The room a voice was recorded in (Phase 15c): measured, then put on a new take.

Pure numpy. `estimate_reverb` reads the speaker's own speech tails — the decay
after each stretch of speech stops — with Schroeder backward integration;
`match_room` puts that much reverb on a dry take; `spectral_match` nudges the
take's long-term spectrum toward the speaker's, never more than a few dB.
Everything is deterministic, and every output keeps its input's length and level.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FRAME = 0.005          # seconds per envelope frame
MIN_RT60 = 0.12        # below this the clip is dry: nothing worth matching
MAX_RT60 = 2.5
MIN_DECAYS = 2
CLAMP_DB = 6.0
_SEED = 15


@dataclass(frozen=True)
class RoomProfile:
    rt60: float          # seconds for the tail to fall 60 dB
    early_ratio: float   # share of a tail's energy in its first 50 ms, 0-1
    decays: int = 0      # how many tails the estimate rests on


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def _envelope_db(x: np.ndarray, sr: int) -> np.ndarray:
    n = max(1, round(FRAME * sr))
    count = len(x) // n
    frames = x[: count * n].reshape(count, n)
    return 10 * np.log10((frames ** 2).mean(axis=1) + 1e-12)


def _tail(seg: np.ndarray, sr: int) -> tuple[float, float] | None:
    """(rt60, early_ratio) of one decay, from its Schroeder curve, or None."""
    energy = seg.astype(np.float64) ** 2
    back = np.cumsum(energy[::-1])[::-1]
    if back[0] <= 0:
        return None
    curve = 10 * np.log10(back / back[0] + 1e-12)
    lo, hi = np.argmax(curve <= -5.0), np.argmax(curve <= -20.0)
    if curve[-1] > -20.0 or hi <= lo + 3:
        return None
    t = np.arange(lo, hi + 1) / sr
    slope = np.polyfit(t, curve[lo:hi + 1], 1)[0]   # dB per second, negative
    if slope >= 0:
        return None
    early = 1.0 - 10 ** (curve[min(len(curve) - 1, round(0.05 * sr))] / 10)
    return -60.0 / slope, float(np.clip(early, 0.0, 1.0))


def estimate_reverb(x: np.ndarray, sr: int) -> RoomProfile | None:
    """RT60 and early ratio from the decays after the speaker stops, or None
    when the clip is too short or too dry to hold a usable one."""
    x = _mono(x)
    if len(x) < sr:
        return None
    env = _envelope_db(x, sr)
    n = max(1, round(FRAME * sr))
    floor, top = np.percentile(env, 10), np.percentile(env, 95)
    if top - floor < 25.0:
        return None
    loud = env >= top - 12.0
    longest = round(1.0 / FRAME)
    found: list[tuple[float, float]] = []
    i = 0
    while i < len(env) - 1:
        # An offset: the last loud frame of a run, followed by a quieter one.
        if not (loud[i] and not loud[i + 1]):
            i += 1
            continue
        j, low = i + 1, env[i + 1]
        while j < min(len(env), i + longest) and env[j] < low + 3.0 and env[j] > floor + 3.0:
            low = min(low, env[j])
            j += 1
        if (j - i) * FRAME >= 0.15:
            tail = _tail(x[(i + 1) * n:j * n], sr)
            if tail is not None:
                found.append(tail)
        i = max(j, i + 1)
    if len(found) < MIN_DECAYS:
        return None
    rt60 = float(np.median([f[0] for f in found]))
    if not MIN_RT60 <= rt60 <= MAX_RT60:
        return None
    return RoomProfile(rt60, float(np.median([f[1] for f in found])), len(found))


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def _convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    size = 1 << (len(x) + len(h) - 2).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)
    return y[: len(x)]


def match_room(voice: np.ndarray, profile: RoomProfile, sr: int) -> np.ndarray:
    """`voice` with the profile's reverb on it: the dry take plus its own
    convolution with an exponentially decaying noise tail, mixed to the
    measured early ratio. Same length, same loudness."""
    x = np.asarray(voice, dtype=np.float64)
    if x.ndim == 2:
        return np.stack([match_room(x[:, c], profile, sr) for c in range(x.shape[1])], axis=1).astype(voice.dtype)
    level = _rms(x)
    if level == 0.0:
        return voice.copy()
    length = max(1, round(min(profile.rt60 * 1.2, MAX_RT60) * sr))
    t = np.arange(length) / sr
    h = np.random.default_rng(_SEED).standard_normal(length) * 10 ** (-3.0 * t / profile.rt60)
    wet = _convolve(x, h)
    # Wet-to-dry energy share: what the early ratio leaves for the late tail.
    share = float(np.clip(1.0 - profile.early_ratio, 0.2, 0.6))
    wet *= np.sqrt(share / (1.0 - share)) * level / max(_rms(wet), 1e-12)
    out = x + wet
    return (out * (level / max(_rms(out), 1e-12))).astype(voice.dtype)


def _average_spectrum(x: np.ndarray, nfft: int) -> np.ndarray:
    """Mean power spectrum over the active (speech) frames."""
    hop = nfft // 2
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    starts = range(0, len(x) - nfft + 1, hop)
    frames = np.stack([x[s:s + nfft] for s in starts]) * np.hanning(nfft)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    level = power.sum(axis=1)
    keep = level >= level.max() * 1e-3 if level.max() > 0 else np.ones(len(level), bool)
    return power[keep].mean(axis=0)


def _third_octave(db: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Smooth a dB curve across a third of an octave (a window in log frequency)."""
    out = db.copy()
    ratio = 2 ** (1 / 6)
    cum = np.concatenate([[0.0], np.cumsum(db)])
    for k in range(1, len(freqs)):
        a = np.searchsorted(freqs, freqs[k] / ratio, side="left")
        b = np.searchsorted(freqs, freqs[k] * ratio, side="right")
        out[k] = (cum[b] - cum[a]) / max(1, b - a)
    return out


def spectral_match(voice: np.ndarray, context: np.ndarray, sr: int) -> np.ndarray:
    """`voice` EQ'd toward the long-term spectrum of `context` (the speaker's
    own speech): a smoothed, zero-phase FIR, at most +/-6 dB in any band.
    Same length, same loudness."""
    x = np.asarray(voice, dtype=np.float64)
    if x.ndim == 2:
        ctx = _mono(context)
        return np.stack([spectral_match(x[:, c], ctx, sr) for c in range(x.shape[1])], axis=1).astype(voice.dtype)
    ctx = _mono(context)
    level = _rms(x)
    if level == 0.0 or _rms(ctx) == 0.0:
        return voice.copy()
    nfft = 2048
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    ratio_db = 10 * np.log10((_average_spectrum(ctx, nfft) + 1e-12) / (_average_spectrum(x, nfft) + 1e-12))
    ratio_db = np.clip(_third_octave(ratio_db, freqs), -CLAMP_DB, CLAMP_DB)
    # Zero phase: a real, even response → symmetric impulse response, windowed.
    taps = 1025
    ir = np.fft.fftshift(np.fft.irfft(10 ** (ratio_db / 20), nfft))
    mid = nfft // 2
    ir = ir[mid - taps // 2: mid + taps // 2 + 1] * np.hanning(taps)
    out = _convolve(np.pad(x, (0, taps // 2)), ir)[taps // 2: taps // 2 + len(x)]
    return (out * (level / max(_rms(out), 1e-12))).astype(voice.dtype)
