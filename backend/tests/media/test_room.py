"""Room estimation and matching, on synthetic signals with a known answer."""
from itertools import pairwise

import numpy as np
import pytest

from app.media import room

SR = 16000


def _bursts(seconds=8.0, burst=0.3, gap=0.9, seed=1):
    """Noise bursts with silence between them: a stand-in for phrases and pauses."""
    rng = np.random.default_rng(seed)
    x = np.zeros(round(seconds * SR))
    t = 0.2
    while t + burst < seconds:
        i = round(t * SR)
        x[i:i + round(burst * SR)] = rng.standard_normal(round(burst * SR)) * 0.2
        t += burst + gap
    return x


def _reverberate(x, rt60, seed=3):
    n = round(rt60 * 1.5 * SR)
    t = np.arange(n) / SR
    h = np.random.default_rng(seed).standard_normal(n) * 10 ** (-3 * t / rt60)
    h[0] = 4.0   # the direct sound
    size = 1 << (len(x) + n).bit_length()
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[: len(x)]


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


@pytest.mark.parametrize("rt60", [0.4, 0.7])
def test_estimate_recovers_the_rt60(rt60):
    wet = _reverberate(_bursts(), rt60)
    profile = room.estimate_reverb(wet, SR)
    assert profile is not None
    assert profile.rt60 == pytest.approx(rt60, rel=0.25)
    assert 0.0 <= profile.early_ratio <= 1.0


def test_a_dry_or_short_clip_has_no_room():
    assert room.estimate_reverb(_bursts(), SR) is None
    assert room.estimate_reverb(_reverberate(_bursts(seconds=0.6), 0.5), SR) is None
    assert room.estimate_reverb(np.zeros(SR * 5), SR) is None


def test_match_room_adds_reverb_and_keeps_length_and_level():
    voice = _bursts(seed=7)
    profile = room.RoomProfile(rt60=0.6, early_ratio=0.7)
    out = room.match_room(voice, profile, SR)
    assert out.shape == voice.shape
    assert abs(_rms_db(out) - _rms_db(voice)) < 1.0
    heard = room.estimate_reverb(out, SR)
    assert heard is not None and heard.rt60 > 0.3
    assert np.array_equal(out, room.match_room(voice, profile, SR))   # deterministic


def test_match_room_leaves_silence_and_dtype_alone():
    quiet = np.zeros(SR, dtype=np.float32)
    out = room.match_room(quiet, room.RoomProfile(0.5, 0.7), SR)
    assert out.dtype == np.float32 and not out.any()


def _tilted(seed, slope):
    """White noise given a spectral tilt of `slope` dB per octave."""
    x = np.random.default_rng(seed).standard_normal(SR * 4)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    gain = (np.maximum(freqs, 100) / 1000) ** (slope / 6.02)
    y = np.fft.irfft(np.fft.rfft(x) * gain, len(x))
    return y / np.sqrt(np.mean(y ** 2)) * 0.1


def _bands(x):
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    edges = [200, 400, 800, 1600, 3200, 6400]
    return np.array([10 * np.log10(spec[(freqs >= a) & (freqs < b)].mean()) for a, b in pairwise(edges)])


def test_spectral_match_moves_toward_the_context_within_the_clamp():
    voice, context = _tilted(1, -3.0), _tilted(2, -1.0)
    out = room.spectral_match(voice, context, SR)
    assert out.shape == voice.shape
    assert abs(_rms_db(out) - _rms_db(voice)) < 0.5
    before, after, target = _bands(voice), _bands(out), _bands(context)
    target, before, after = (v - v.mean() for v in (target, before, after))
    assert np.abs(after - target).mean() < np.abs(before - target).mean()
    # No band moved by more than the clamp (plus a little for smoothing/skirts).
    assert np.abs(after - before).max() <= room.CLAMP_DB * 2 + 1.0
