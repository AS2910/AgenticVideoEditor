"""Run 4, item 3c: the cheaper true-peak pass gives what the whole-mix one gave.

The reference below is the implementation as it was (every 5 s oversampled
4x by FFT, and a last limit after the loop): the new one oversamples only the
stretches within the overshoot of the level that matters, and does not limit
twice. On speech, a clipped sine, an intersample-peak signal and silence the
loudness must agree within 0.05 LU and the true peak within 0.1 dB."""
import math
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from app.media import loudness as L

RATE = 48000
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "silent-tail-zh.wav"


# ── the reference: the old implementation, verbatim ──────────────────────────

def ref_true_peak_db(x, rate=RATE):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if len(x) == 0:
        return -math.inf
    peak = float(np.abs(x).max())
    chunk, pad = rate * 5, 256
    for i in range(0, len(x), chunk):
        part = x[max(0, i - pad): i + chunk + pad]
        size = len(part)
        up = np.fft.irfft(np.fft.rfft(part, axis=0), size * 4, axis=0) * 4
        peak = max(peak, float(np.abs(up).max()))
    return 20 * math.log10(peak) if peak > 0 else -math.inf


def _ref_frame_true_peaks(x, frame, rate):
    frames = math.ceil(len(x) / frame)
    out = np.zeros(frames)
    chunk, pad = (rate * 5 // frame) * frame, 256
    for i in range(0, len(x), chunk):
        lo = max(0, i - pad)
        part = x[lo: i + chunk + pad]
        up = np.abs(np.fft.irfft(np.fft.rfft(part, axis=0), len(part) * 4, axis=0) * 4).max(axis=1)
        own = up[(i - lo) * 4: (i - lo + min(chunk, len(x) - i)) * 4]
        n = len(own) // (frame * 4)
        f0 = i // frame
        if n:
            out[f0: f0 + n] = own[: n * frame * 4].reshape(n, frame * 4).max(axis=1)
        rest = own[n * frame * 4:]
        if rest.size and f0 + n < frames:
            out[f0 + n] = max(out[f0 + n], rest.max())
    return out


def ref_limit(x, ceiling_db=-1.0, rate=RATE, lookahead=0.005, release=0.05):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    ceiling = L.gain(ceiling_db)
    frame = max(1, rate // 1000)
    peaks = _ref_frame_true_peaks(x, frame, rate)
    need = np.minimum(1.0, ceiling / np.maximum(peaks, 1e-12))
    if need.min() >= 1.0:
        return x
    ahead = max(1, round(lookahead * rate / frame))
    padded = np.concatenate([need, np.ones(ahead)])
    windows = np.lib.stride_tricks.sliding_window_view(padded, ahead + 1)
    lowest = windows.min(axis=1)[: len(need)]
    ramp = np.convolve(np.concatenate([np.full(ahead, lowest[0]), lowest]), np.ones(ahead) / ahead, mode="valid")[: len(need)]
    ramp = np.minimum(ramp, lowest)
    coef = 1 - math.exp(-frame / (release * rate))
    env = np.empty_like(ramp)
    level = 1.0
    for i, g in enumerate(ramp):
        level = g if g < level else level + (g - level) * coef
        env[i] = level
    per_sample = np.interp(np.arange(len(x)) / frame, np.arange(len(env)), env)
    out = x * per_sample[:, None]
    over = ref_true_peak_db(out, rate) - ceiling_db
    return out * L.gain(-over - 0.01) if over > 0 else out


def ref_normalize(x, target_lufs, ceiling_db=-1.0, rate=RATE):
    x = np.asarray(x, dtype=np.float64)
    out = x
    for _ in range(3):
        now = L.loudness(out, rate)
        if now <= L.SILENCE:
            return x, L.SILENCE
        if abs(now - target_lufs) <= 0.2:
            break
        out = ref_limit(out * L.gain(target_lufs - now), ceiling_db, rate)
    out = ref_limit(out, ceiling_db, rate)
    return out, L.loudness(out, rate)


# ── the signals ──────────────────────────────────────────────────────────────

def speech(seconds=10.0):
    """The speech fixture (16 kHz mono), at 48 kHz, tiled to `seconds`, stereo with a little width."""
    with wave.open(str(FIXTURE)) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
        rate = w.getframerate()
    t = np.arange(int(len(raw) * RATE / rate)) / RATE
    up = np.interp(t, np.arange(len(raw)) / rate, raw)
    x = np.tile(up, math.ceil(seconds * RATE / len(up)))[: int(seconds * RATE)]
    return np.stack([x, np.roll(x, 7) * 0.9], axis=1)


def faded(x, ms=10):
    """In and out over `ms`, as a mix of real audio starts and ends (the two meters differ only
    on a signal that starts or stops at full level: see test_an_abrupt_start_reads_higher_never_lower)."""
    n = int(RATE * ms / 1000)
    ramp = np.ones(len(x))
    ramp[:n] = np.linspace(0, 1, n)
    ramp[-n:] = np.linspace(1, 0, n)
    return x * ramp[:, None]


def clipped_sine(seconds=4.0, fade=True):
    t = np.arange(int(seconds * RATE)) / RATE
    x = np.clip(3 * np.sin(2 * np.pi * 997 * t), -1, 1) * 0.5
    x = np.stack([x, x], axis=1)
    return faded(x) if fade else x


def intersample(seconds=4.0):
    """A tone at a quarter of the rate, 45 degrees off: samples at 0.707, true peak 1.0 (+3 dB)."""
    n = np.arange(int(seconds * RATE))
    x = np.sin(np.pi / 2 * n + np.pi / 4)
    return faded(np.stack([x, x * 0.5], axis=1))


def bursts(seconds=12.0, seed=3):
    """Loud and quiet stretches: most of it far under the loudest, so most is never oversampled."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    level = np.where((t % 3) < 0.4, 0.9, 0.03)
    x = rng.normal(0, 1, len(t)) * level * 0.3 + np.sin(2 * np.pi * 220 * t) * level
    return np.stack([x, x[::-1]], axis=1)


SIGNALS = {"speech": speech, "clipped sine": clipped_sine, "intersample": intersample, "bursts": bursts}


@pytest.mark.parametrize("name", list(SIGNALS))
def test_the_true_peak_matches_the_whole_mix_oversampling(name):
    x = SIGNALS[name]()
    for scale in (1.0, 0.25, 2.0):
        assert L.true_peak_db(x * scale) == pytest.approx(ref_true_peak_db(x * scale), abs=0.1)


def test_an_abrupt_start_reads_higher_never_lower():
    """A clip that starts and stops at full level: before and after it is silence, so its
    edges never read lower than the old wrap-around did (the limiter errs safe)."""
    x = np.roll(clipped_sine(fade=False), 11, axis=0)
    assert L.true_peak_db(x) >= ref_true_peak_db(x) - 0.01


def test_the_intersample_peak_is_found():
    x = intersample()
    assert float(np.abs(x).max()) == pytest.approx(math.sqrt(0.5), abs=1e-6)
    assert L.true_peak_db(x) == pytest.approx(0.0, abs=0.05)


@pytest.mark.parametrize("name", list(SIGNALS))
@pytest.mark.parametrize("target", [-14.0, -23.0])
def test_normalize_lands_where_it_did(name, target):
    x = SIGNALS[name]()
    new, new_lufs = L.normalize(x, target, -1.0)
    old, old_lufs = ref_normalize(x, target, -1.0)
    assert new_lufs == pytest.approx(old_lufs, abs=0.05)
    assert L.loudness(new) == pytest.approx(L.loudness(old), abs=0.05)
    assert ref_true_peak_db(new) == pytest.approx(ref_true_peak_db(old), abs=0.1)
    assert ref_true_peak_db(new) <= -1.0 + 1e-6                     # never over the ceiling, by the old meter


@pytest.mark.parametrize("name", list(SIGNALS))
def test_the_limiter_does_what_it_did(name):
    x = SIGNALS[name]() * 2.5                                        # well over the ceiling
    new, old = L.limit(x, -1.0), ref_limit(x, -1.0)
    assert ref_true_peak_db(new) == pytest.approx(ref_true_peak_db(old), abs=0.1)
    assert L.loudness(new) == pytest.approx(L.loudness(old), abs=0.05)
    assert float(np.abs(new - old).max()) < 0.01


def test_silence_stays_silence():
    x = np.zeros((RATE * 3, 2))
    assert L.true_peak_db(x) == ref_true_peak_db(x) == -math.inf
    out, lufs = L.normalize(x, -14.0)
    assert lufs == L.SILENCE and not out.any()
    assert L.limit(x).shape == x.shape and not L.limit(x).any()


def test_it_is_cheaper():
    x = speech(30.0)
    t0 = time.perf_counter(); ref_normalize(x, -14.0); old = time.perf_counter() - t0
    t0 = time.perf_counter(); L.normalize(x, -14.0); new = time.perf_counter() - t0
    assert new < old, (new, old)
