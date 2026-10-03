"""Phase 14: syllable budgets and gap-first fitting. Needs ffmpeg for the
final exact trim; the gap work itself is numpy."""
import wave
from pathlib import Path

import numpy as np
import pytest

from app.domain.models import Statement, Transcript, Word
from app.media import ffmpeg
from app.media.fit import (
    DEFAULT_RATE, find_gaps, fit_elastically, place, speaking_rate, syllable_budget, syllables,
)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")

RATE = 24000


def test_syllables_are_counted_roughly_but_sensibly():
    assert syllables("Get 20% off today only.") == 1 + 4 + 1 + 2 + 2   # "20%" reads as "twenty percent"
    assert syllables("Start a live Bajicam session.") == 1 + 1 + 1 + 3 + 2
    assert syllables("the") == 1 and syllables("table") == 2 and syllables("") == 0


def test_speaking_rate_is_the_speakers_own_or_everyones():
    t = Transcript(words=(), statements=(
        Statement("Hi, I want to buy groceries.", 0.0, 1.8, "A"),            # 8 syl / 1.8 s
        Statement("Sure, sir.", 2.0, 2.5, "B"),
        Statement("We also have organic imported ones.", 3.0, 5.6, "B"),    # 12 / 2.6
    ))
    assert speaking_rate(t, "B") == pytest.approx((2 + 12) / 3.1, rel=0.01)   # B has 3.1 s: enough to trust
    assert speaking_rate(t, "A") == speaking_rate(t)                          # A alone is too short
    assert speaking_rate(Transcript(words=())) == DEFAULT_RATE


def test_the_budget_is_rate_times_seconds():
    assert syllable_budget(4.5, 2.0) == 9
    assert syllable_budget(4.5, 0.1) == 1


def _tone(seconds, freq=440.0):
    t = np.arange(int(RATE * seconds)) / RATE
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(seconds):
    return np.zeros(int(RATE * seconds), dtype=np.float32)


def _write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def two_words(tmp_path, lead=0.1, gap=0.4, tail=0.1):
    """"word" (0.5 s) pause "word" (0.5 s), with silence around."""
    x = np.concatenate([_silence(lead), _tone(0.5), _silence(gap), _tone(0.5, 660), _silence(tail)])
    path = tmp_path / "take.wav"
    _write(path, x)
    return path, len(x) / RATE


def test_gaps_are_found_with_their_edges(tmp_path):
    path, _ = two_words(tmp_path)
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    gaps = find_gaps(x, RATE)
    seconds = [(g.start / RATE, g.end / RATE) for g in gaps]
    assert len(seconds) == 3
    assert seconds[0] == pytest.approx((0.0, 0.1), abs=0.02)
    assert seconds[1] == pytest.approx((0.6, 1.0), abs=0.02)
    assert seconds[2][1] == pytest.approx(1.6, abs=0.02)


@needs_ffmpeg
def test_a_long_take_loses_pause_before_speech_is_sped_up(tmp_path):
    path, natural = two_words(tmp_path)        # 1.6 s, 0.6 s of which is silence
    target = 1.35                               # uniform tempo would be 1.19×

    out, duration, notes = fit_elastically(path, tmp_path / "fit.wav", target)

    assert duration == pytest.approx(target, abs=0.02)
    assert any(n.startswith("trimmed") for n in notes)
    # The pauses gave up most of the 0.25 s, so the speech itself barely moved.
    assert not any("speed" in n for n in notes)


@needs_ffmpeg
def test_a_short_take_opens_its_pauses_before_it_is_slowed(tmp_path):
    path, natural = two_words(tmp_path, gap=0.3)   # 1.5 s
    target = 1.65
    out, duration, notes = fit_elastically(path, tmp_path / "fit.wav", target)
    assert duration == pytest.approx(target, abs=0.02)
    assert any(n.startswith("opened") for n in notes)


@needs_ffmpeg
def test_within_tolerance_nothing_but_the_exact_trim_happens(tmp_path):
    path, natural = two_words(tmp_path)
    out, duration, notes = fit_elastically(path, tmp_path / "fit.wav", natural * 1.02)
    assert duration == pytest.approx(natural * 1.02, abs=0.02) and notes == []


@needs_ffmpeg
def test_far_too_long_still_asks_with_the_trimmed_length(tmp_path):
    path, natural = two_words(tmp_path)
    with pytest.raises(ffmpeg.SpanMismatch) as exc:
        fit_elastically(path, tmp_path / "fit.wav", 0.7)
    assert 0.9 < exc.value.natural < natural      # the pauses were already taken out


@needs_ffmpeg
def test_place_keeps_the_explicit_fits_as_they_were(tmp_path):
    path, natural = two_words(tmp_path)
    _, duration, notes = place(path, tmp_path / "s.wav", 2.5, fit="stretch")
    assert duration == pytest.approx(2.5, abs=0.02) and notes == []
    _, duration, _ = place(path, tmp_path / "c.wav", 0.3, mix="concatenate")
    assert duration == pytest.approx(natural, abs=0.02)
