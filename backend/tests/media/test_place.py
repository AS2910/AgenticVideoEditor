"""Placing a line in a selection the way the user chose (Phase 8)."""
import pytest

from app.media import ffmpeg

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


@pytest.fixture()
def line(tmp_path):
    path, _ = ffmpeg.generate_tone(tmp_path / "line.wav", 1.0, 300)
    return path


@pytest.mark.parametrize("tempo", [0.19, 0.5, 1.0, 1.7, 5.0])
def test_atempo_chain_multiplies_out_to_the_tempo(tempo):
    stages = [float(s.split("=")[1]) for s in ffmpeg.atempo_chain(tempo).split(",")]
    assert all(0.5 <= s <= 2.0 for s in stages)
    product = 1.0
    for s in stages:
        product *= s
    assert product == pytest.approx(tempo, rel=1e-4)


def test_auto_fit_still_refuses_a_far_stretch(line, tmp_path):
    with pytest.raises(ffmpeg.SpanMismatch):
        ffmpeg.place(line, tmp_path / "o.wav", 3.87)


@pytest.mark.parametrize("target", [3.87, 0.3])
def test_stretch_fills_the_selection_however_far(line, tmp_path, target):
    _, duration = ffmpeg.place(line, tmp_path / "o.wav", target, fit="stretch")
    assert duration == pytest.approx(target, abs=0.02)


def test_start_pads_a_short_line_to_the_selection(line, tmp_path):
    _, duration = ffmpeg.place(line, tmp_path / "o.wav", 2.5, fit="start")
    assert duration == pytest.approx(2.5, abs=0.02)


def test_start_keeps_a_long_line_whole(line, tmp_path):
    _, duration = ffmpeg.place(line, tmp_path / "o.wav", 0.4, fit="start")
    assert duration == pytest.approx(1.0, abs=0.02)


def test_concatenate_keeps_the_natural_length_whatever_the_fit(line, tmp_path):
    _, duration = ffmpeg.place(line, tmp_path / "o.wav", 3.0, fit=None, mix="concatenate")
    assert duration == pytest.approx(1.0, abs=0.02)


def test_natural_range():
    assert ffmpeg.natural_range(1.0, 1.1)
    assert not ffmpeg.natural_range(0.74, 3.87)
