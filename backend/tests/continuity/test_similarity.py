"""SIM-o and naturalness with fake models: nothing here loads a network."""
import numpy as np
import pytest

from app.continuity import measured, similarity
from app.media import ffmpeg

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


def wav(tmp_path, name, seconds=2.0, freq=220.0):
    t = np.arange(int(seconds * 16000)) / 16000
    path = tmp_path / name
    measured._write_wav(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), 16000)
    return path


def spectrum(x):
    """A stand-in embedder: the dominant frequency decides the vector."""
    peak = np.argmax(np.abs(np.fft.rfft(x))) * 16000 / x.size
    angle = peak / 1000
    return np.array([np.cos(angle), np.sin(angle)])


def test_the_same_audio_scores_one(tmp_path):
    a = wav(tmp_path, "a.wav")
    assert similarity.speaker_similarity(a, a, embed=spectrum) == pytest.approx(1.0)


def test_a_different_voice_scores_lower(tmp_path):
    a, b = wav(tmp_path, "a.wav", freq=220), wav(tmp_path, "b.wav", freq=900)
    score = similarity.speaker_similarity(a, b, embed=spectrum)
    assert 0.0 <= score < 0.9


def test_a_negative_cosine_clamps_to_zero(tmp_path):
    a, b = wav(tmp_path, "a.wav"), wav(tmp_path, "b.wav", freq=300)
    calls = iter([np.array([1.0, 0.0]), np.array([-1.0, 0.0])])
    assert similarity.speaker_similarity(a, b, embed=lambda x: next(calls)) == 0.0


def test_audio_under_half_a_second_is_not_judged(tmp_path):
    a, short = wav(tmp_path, "a.wav"), wav(tmp_path, "s.wav", seconds=0.3)
    assert similarity.speaker_similarity(a, short, embed=spectrum) is None
    assert similarity.speaker_similarity(short, a, embed=spectrum) is None
    assert similarity.naturalness(short, predict=lambda x: 4.0) is None


def test_a_model_that_cannot_load_gives_none(tmp_path, monkeypatch):
    a = wav(tmp_path, "a.wav")
    monkeypatch.setattr(similarity, "_embedder", None)
    monkeypatch.setattr(similarity, "_predictor", None)
    monkeypatch.setattr(similarity, "_failed", {"embed", "predict"})
    assert similarity.speaker_similarity(a, a) is None
    assert similarity.naturalness(a) is None


def test_a_model_that_raises_gives_none_not_an_error(tmp_path):
    a = wav(tmp_path, "a.wav")

    def boom(x):
        raise RuntimeError("out of memory")

    assert similarity.speaker_similarity(a, a, embed=boom) is None
    assert similarity.naturalness(a, predict=boom) is None


def test_a_zero_vector_gives_none(tmp_path):
    a = wav(tmp_path, "a.wav")
    assert similarity.speaker_similarity(a, a, embed=lambda x: np.zeros(2)) is None


def test_naturalness_is_the_models_mos_kept_in_range(tmp_path):
    a = wav(tmp_path, "a.wav")
    assert similarity.naturalness(a, predict=lambda x: 3.7) == pytest.approx(3.7)
    assert similarity.naturalness(a, predict=lambda x: 9.0) == 5.0


def test_available_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("AVE_MEASURE", "0")
    assert similarity.available() is False
