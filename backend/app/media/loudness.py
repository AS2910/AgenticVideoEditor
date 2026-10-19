"""Loudness as people hear it (2026-10-20): ITU-R BS.1770 / EBU R128 in numpy.

The mix sets every level in LUFS, not in raw gain, so a narration, a bed of
cheers and an effect are placed against how loud the clip's own speech
sounds. Here: K-weighting (applied in the frequency domain; the loudness of a
block depends on its power, not its phase), gated loudness of a signal or of
the parts of it a mask keeps, true peak by 4x oversampling, a look-ahead
limiter, and the smoothed gain ramps the ducking uses.

Checked against ffmpeg's own ebur128 meter in the tests.
"""
from __future__ import annotations

import math

import numpy as np

RATE = 48000
SILENCE = -70.0          # the absolute gate, and what silence reads as
BLOCK = 0.4              # seconds per gating block
STEP = 0.1               # 75% overlap


def _biquad_response(b, a, w: np.ndarray) -> np.ndarray:
    z = np.exp(-1j * w)
    return (b[0] + b[1] * z + b[2] * z ** 2) / (a[0] + a[1] * z + a[2] * z ** 2)


def _k_filters(rate: int):
    """The two K-weighting stages (a high shelf for the head, a high-pass)
    designed for `rate`, as in BS.1770 (its 48 kHz table, generalised)."""
    # Stage 1: high shelf, +4 dB above about 1.5 kHz.
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / rate)
    vh, vb = 10 ** (gain / 20), (10 ** (gain / 20)) ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    b1 = ((vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0)
    a1 = (1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    # Stage 2: high-pass at about 38 Hz.
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / rate)
    a0 = 1 + k / q + k * k
    b2 = (1.0, -2.0, 1.0)
    a2 = (1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    return (b1, a1), (b2, a2)


def _fast_len(n: int) -> int:
    """A length at least `n` whose FFT is quick (a product of 2, 3 and 5)."""
    best = 1 << max(0, (n - 1).bit_length())
    for p3 in (1, 3, 9, 27):
        for p5 in (1, 5, 25):
            m = p3 * p5
            while m < n:
                m *= 2
            best = min(best, m)
    return best


def k_weighted(x: np.ndarray, rate: int = RATE) -> np.ndarray:
    """`x` (samples,) or (samples, channels) through the K-weighting filter."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    n = len(x)
    if n == 0:
        return x
    size = _fast_len(n + 2048)
    w = 2 * np.pi * np.fft.rfftfreq(size, 1 / rate) / rate
    (b1, a1), (b2, a2) = _k_filters(rate)
    h = np.abs(_biquad_response(b1, a1, w) * _biquad_response(b2, a2, w))
    spectrum = np.fft.rfft(x, size, axis=0) * h[:, None]
    return np.fft.irfft(spectrum, size, axis=0)[:n]


def _block_powers(y: np.ndarray, rate: int) -> np.ndarray:
    """Mean K-weighted power per 400 ms block (75% overlap), summed over channels."""
    block, step = int(BLOCK * rate), int(STEP * rate)
    power = (y ** 2).sum(axis=1)
    if len(power) <= block:
        return np.array([power.mean()]) if len(power) else np.zeros(0)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, len(power) - block + 1, step)
    return (csum[starts + block] - csum[starts]) / block


def _lufs(p):
    return -0.691 + 10 * np.log10(np.maximum(p, 1e-12))


def loudness(x: np.ndarray, rate: int = RATE, mask: np.ndarray | None = None) -> float:
    """Integrated, gated loudness in LUFS; SILENCE for silence. With `mask`
    (one bool per sample), only the samples it keeps are measured, joined:
    the loudness of the words, say, and not of the pauses between them."""
    y = k_weighted(x, rate)
    if mask is not None:
        y = y[np.asarray(mask, dtype=bool)[: len(y)]]
    powers = _block_powers(y, rate)
    if powers.size == 0:
        return SILENCE
    loud = powers[_lufs(powers) > SILENCE]
    if loud.size == 0:
        return SILENCE
    relative = _lufs(loud.mean()) - 10
    kept = loud[_lufs(loud) > relative]
    return float(_lufs((kept if kept.size else loud).mean()))


def gain(db: float) -> float:
    return float(10 ** (db / 20))


def true_peak_db(x: np.ndarray, rate: int = RATE) -> float:
    """The true peak in dBTP, by 4x oversampling (in chunks, with overlap)."""
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


def _frame_true_peaks(x: np.ndarray, frame: int, rate: int) -> np.ndarray:
    """The true peak of every `frame` samples, linear."""
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


def limit(x: np.ndarray, ceiling_db: float = -1.0, rate: int = RATE,
          lookahead: float = 0.005, release: float = 0.05) -> np.ndarray:
    """A look-ahead true-peak limiter: the gain comes down smoothly before a
    peak and recovers after it, so nothing clips and nothing clicks."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    ceiling = gain(ceiling_db)
    frame = max(1, rate // 1000)
    peaks = _frame_true_peaks(x, frame, rate)
    need = np.minimum(1.0, ceiling / np.maximum(peaks, 1e-12))
    if need.min() >= 1.0:
        return x
    ahead = max(1, round(lookahead * rate / frame))
    padded = np.concatenate([need, np.ones(ahead)])
    windows = np.lib.stride_tricks.sliding_window_view(padded, ahead + 1)
    lowest = windows.min(axis=1)[: len(need)]
    # A ramp down over the look-ahead (no step), then a smooth release.
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
    # The ramp's last fraction of a dB, made certain.
    over = true_peak_db(out, rate) - ceiling_db
    return out * gain(-over - 0.01) if over > 0 else out


def normalize(x: np.ndarray, target_lufs: float, ceiling_db: float = -1.0, rate: int = RATE) -> tuple[np.ndarray, float]:
    """`x` at `target_lufs` with its true peak at or under `ceiling_db`.
    Returns the result and the loudness it measures. Silence stays silence."""
    x = np.asarray(x, dtype=np.float64)
    out = x
    for _ in range(3):
        now = loudness(out, rate)
        if now <= SILENCE:
            return x, SILENCE
        if abs(now - target_lufs) <= 0.2:
            break
        # Each pass corrects the loudness the limiter took away the pass before.
        boost = target_lufs - now
        out = limit(out * gain(boost), ceiling_db, rate)
    out = limit(out, ceiling_db, rate)
    return out, loudness(out, rate)


def ramp_envelope(active: np.ndarray, low_db: float, samples: int, rate: int = RATE,
                  attack: float = 0.15, release: float = 0.4, frame_s: float = 0.01) -> np.ndarray:
    """A per-sample gain: `low_db` where `active` (one bool per 10 ms frame),
    unity elsewhere, going down over `attack` and back up over `release`
    seconds. Smooth both ways, so a duck never clicks."""
    target = np.where(np.asarray(active, dtype=bool), gain(low_db), 1.0)
    if target.size == 0:
        return np.ones(samples)
    down, up = frame_s / max(attack, 1e-3), frame_s / max(release, 1e-3)
    span = 1.0 - gain(low_db)
    env = np.empty_like(target)
    level = 1.0
    for i, t in enumerate(target):
        if t < level:
            level = max(t, level - span * down)
        else:
            level = min(t, level + span * up)
        env[i] = level
    frame = rate * frame_s
    return np.interp(np.arange(samples), np.arange(len(env)) * frame + frame / 2, env).astype(np.float64)


def frames_active(x: np.ndarray, rate: int = RATE, frame_s: float = 0.01, below_db: float = 30.0, hang: float = 0.1) -> np.ndarray:
    """Which 10 ms frames carry sound: within `below_db` of the loudest frame,
    held a little after, so the gaps between words are not dips."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    frame = max(1, int(rate * frame_s))
    n = len(x) // frame
    if n == 0:
        return np.zeros(0, dtype=bool)
    rms = np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    top = rms.max()
    if top <= 1e-6:
        return np.zeros(n, dtype=bool)
    on = rms > top * gain(-below_db)
    keep = max(1, int(hang / frame_s))
    out = on.copy()
    for k in range(1, keep + 1):
        out[k:] |= on[:-k]
    return out
