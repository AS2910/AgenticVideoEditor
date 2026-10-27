"""Run 5 item 8: music or noise under the speech, heard on upload."""
import numpy as np
import pytest

from app.media import bed, ffmpeg

RATE = bed.RATE


def _speech(seconds=8.0, seed=1):
    """Noise bursts with dead silence between them: words and pauses."""
    rng = np.random.default_rng(seed)
    x = np.zeros(round(seconds * RATE))
    for t in np.arange(0.2, seconds - 0.6, 0.9):
        i = round(t * RATE)
        x[i:i + round(0.5 * RATE)] = rng.standard_normal(round(0.5 * RATE)) * 0.2
    return x


def _at(x, db_under, ref):
    return x * (ref * 10 ** (-db_under / 20) / np.sqrt(np.mean(x ** 2)))


def test_a_clean_recording_has_no_bed():
    assert bed.measure(_speech()).kind == "none"
    assert not bed.measure(_speech()).present


def test_music_under_the_speech_is_heard_as_music():
    x = _speech()
    t = np.arange(len(x)) / RATE
    chord = np.sin(2 * np.pi * 220 * t) + 0.6 * np.sin(2 * np.pi * 277 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)
    found = bed.measure(x + _at(chord, 12, 0.2))
    assert found.kind == "music" and found.gap_db < bed.BED_GAP_DB


def test_noise_under_the_speech_is_heard_as_noise():
    x = _speech()
    hiss = np.random.default_rng(9).standard_normal(len(x))
    assert bed.measure(x + _at(hiss, 10, 0.2)).kind == "noise"


def test_a_quiet_room_is_not_a_bed():
    """A real room's own hiss far under the speech (40 dB) is left alone."""
    x = _speech()
    hiss = np.random.default_rng(9).standard_normal(len(x))
    assert bed.measure(x + _at(hiss, 45, 0.2)).kind == "none"


def test_too_short_to_tell_is_none():
    assert bed.measure(np.zeros(100)).kind == "none"


@pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
def test_detect_reads_a_file_and_never_raises(tmp_path):
    from app.render import compose
    path = tmp_path / "a.wav"
    x = _speech()
    compose._write(path, np.repeat(x.astype(np.float32), compose.OUT_RATE // RATE).reshape(-1, 1))
    assert bed.detect(path).kind == "none"
    assert bed.detect(tmp_path / "missing.mp4") is None
