"""Signal measurements on synthetic audio whose true values are known."""
import numpy as np
import pytest

from app.continuity import signals
from app.media import ffmpeg

RATE = signals.RATE


def tone(freq: float, seconds: float, dbfs: float = -20.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    # A sine's RMS is peak/√2, so scale the peak to hit the requested RMS level.
    return (10 ** (dbfs / 20) * np.sqrt(2) * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def noise(seconds: float, dbfs: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(RATE * seconds))
    return (x / np.sqrt(np.mean(x ** 2)) * 10 ** (dbfs / 20)).astype(np.float32)


@pytest.mark.parametrize("freq", [110.0, 220.0, 330.0])
def test_pitch_of_a_tone_is_its_frequency(freq):
    assert signals.median_f0(tone(freq, 1.0)) == pytest.approx(freq, rel=0.02)


def test_pitch_does_not_jump_an_octave_on_a_harmonic_rich_tone():
    t = np.arange(RATE) / RATE
    x = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 6)).astype(np.float32) * 0.1
    assert signals.median_f0(x) == pytest.approx(150, rel=0.03)


def test_silence_and_noise_have_no_pitch():
    assert signals.median_f0(np.zeros(RATE, dtype=np.float32)) is None
    assert signals.median_f0(noise(1.0, -20)) is None


@pytest.mark.parametrize("level", [-12.0, -20.0, -35.0])
def test_speech_level_reads_the_rms_level(level):
    assert signals.speech_level_db(tone(200, 1.0, level)) == pytest.approx(level, abs=0.5)


def test_speech_level_ignores_the_silence_around_speech():
    x = np.concatenate([np.zeros(RATE), tone(200, 0.5, -20), np.zeros(RATE)])
    assert signals.speech_level_db(x) == pytest.approx(-20, abs=0.5)


def test_silence_has_no_speech_level():
    assert signals.speech_level_db(np.zeros(RATE, dtype=np.float32)) is None


def test_noise_floor_reads_the_quiet_parts():
    x = np.concatenate([noise(1.0, -50), tone(200, 1.0, -20), noise(1.0, -50, seed=1)])
    assert signals.noise_floor_db(x) == pytest.approx(-50, abs=2)


def test_digital_silence_floor_is_clamped_not_minus_infinity():
    assert signals.noise_floor_db(np.zeros(RATE, dtype=np.float32)) == signals.FLOOR_DB


def test_words_per_second():
    assert signals.words_per_second("thirty percent off", 1.5) == pytest.approx(2.0)
    assert signals.words_per_second("", 1.0) is None
    assert signals.words_per_second("hi", 0.0) is None


@pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
def test_load_reads_a_span_of_a_file_as_mono_16k(tmp_path):
    # 300 Hz: inside the 75-400 Hz speech range the pitch tracker searches.
    path, _ = ffmpeg.generate_tone(tmp_path / "t.wav", 2.0, 300, sample_rate=24000)
    x = signals.load(path, 0.5, 1.5)
    assert x.dtype == np.float32
    assert len(x) == pytest.approx(RATE, abs=RATE * 0.01)
    assert signals.median_f0(x) == pytest.approx(300, rel=0.02)
    assert len(signals.load(path)) == pytest.approx(2 * RATE, abs=RATE * 0.01)
