"""The loudness meter, against ffmpeg's own EBU R128 scanner."""
import re
import subprocess
import wave

import numpy as np
import pytest

from app.media import ffmpeg, loudness as L

RATE = 48000


def _wav(path, x):
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())


def _ffmpeg_lufs(path):
    out = subprocess.run([ffmpeg.FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = out[out.rindex("Summary:"):]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1)), float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1))


def _program(seconds=6.0, seed=1):
    """Speech-like: noise bursts at varying levels with pauses, stereo."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    env = (np.sin(2 * np.pi * 3 * t) > -0.2) * (0.3 + 0.7 * (np.sin(2 * np.pi * 0.4 * t) + 1) / 2)
    tone = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * rng.standard_normal(len(t))
    x = (tone * env)[:, None] * np.array([[1.0, 0.8]])
    return x.astype(np.float64)


@pytest.mark.parametrize("seed,scale", [(1, 1.0), (2, 0.2), (3, 0.05)])
def test_loudness_matches_ffmpeg_within_a_tenth(tmp_path, seed, scale):
    x = _program(seed=seed) * scale
    _wav(tmp_path / "x.wav", x)
    ours = L.loudness(x)
    theirs, _ = _ffmpeg_lufs(tmp_path / "x.wav")
    assert ours == pytest.approx(theirs, abs=0.3)


def test_silence_reads_as_silence():
    assert L.loudness(np.zeros((RATE, 2))) == L.SILENCE


def test_a_mask_measures_only_what_it_keeps():
    x = _program()
    loud_half = np.zeros(len(x), dtype=bool); loud_half[: len(x) // 2] = True
    quiet = x.copy(); quiet[len(x) // 2:] *= 0.1
    assert L.loudness(quiet, mask=loud_half) == pytest.approx(L.loudness(x, mask=loud_half), abs=0.01)


def test_normalize_lands_on_target_with_no_true_peak_over(tmp_path):
    x = _program() * 0.05
    x[RATE: RATE + 50] = 0.9   # a click that would clip once raised
    out, got = L.normalize(x, -14.0, -1.0)
    assert got == pytest.approx(-14.0, abs=0.5)
    assert L.true_peak_db(out) <= -0.99
    _wav(tmp_path / "n.wav", out)
    theirs, _ = _ffmpeg_lufs(tmp_path / "n.wav")
    assert theirs == pytest.approx(-14.0, abs=0.5)


def test_the_duck_ramps_and_never_steps():
    active = np.zeros(200, dtype=bool); active[50:120] = True     # 0.5 s to 1.2 s
    env = L.ramp_envelope(active, -6.0, 2 * RATE)
    assert env[int(0.3 * RATE)] == pytest.approx(1.0)
    assert env[int(0.9 * RATE)] == pytest.approx(L.gain(-6.0), abs=1e-3)   # down after 150 ms of attack
    assert np.abs(np.diff(env)).max() < 1e-4                                 # no step anywhere
    assert env[int(1.35 * RATE)] < 0.95 and env[int(1.65 * RATE)] == pytest.approx(1.0)   # a 400 ms release
