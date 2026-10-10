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

    out, duration, notes, _ = fit_elastically(path, tmp_path / "fit.wav", target)

    assert duration == pytest.approx(target, abs=0.02)
    assert any(n.startswith("trimmed") for n in notes)
    # The pauses gave up most of the 0.25 s, so the speech itself barely moved.
    assert not any("speed" in n for n in notes)


@needs_ffmpeg
def test_a_short_take_opens_its_pauses_before_it_is_slowed(tmp_path):
    path, natural = two_words(tmp_path, gap=0.3)   # 1.5 s
    target = 1.65
    out, duration, notes, _ = fit_elastically(path, tmp_path / "fit.wav", target)
    assert duration == pytest.approx(target, abs=0.02)
    assert any(n.startswith("opened") for n in notes)


@needs_ffmpeg
def test_within_tolerance_nothing_but_the_exact_trim_happens(tmp_path):
    path, natural = two_words(tmp_path)
    out, duration, notes, _ = fit_elastically(path, tmp_path / "fit.wav", natural * 1.02)
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
    _, duration, notes, _ = place(path, tmp_path / "s.wav", 2.5, fit="stretch")
    assert duration == pytest.approx(2.5, abs=0.02) and notes == []
    _, duration, _, _ = place(path, tmp_path / "c.wav", 0.3, mix="concatenate")
    assert duration == pytest.approx(natural, abs=0.02)


# --- P-3: the take's own word times -------------------------------------------

from app.media.fit import GapEdit, remap_times, remap_words  # noqa: E402


def test_a_quiet_stretch_inside_a_word_is_not_a_gap(tmp_path):
    path, _ = two_words(tmp_path)
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    # The vendor says the first word runs over the pause: that quiet is speech.
    words = (Word("first", 0.1, 1.0), Word("second", 1.0, 1.5))
    seconds = [(g.start / RATE, g.end / RATE) for g in find_gaps(x, RATE, words)]
    assert len(seconds) == 2
    assert seconds[0] == pytest.approx((0.0, 0.1), abs=0.02)      # the lead-in stays a gap
    assert seconds[1][0] == pytest.approx(1.5, abs=0.02)          # and the tail


def test_times_move_through_cuts_and_grown_gaps_and_a_tempo_change():
    # 100 samples cut from [1000, 1100); 50 samples grown at 3000; rate 1000.
    edits = [GapEdit(1000, 1100, 0), GapEdit(3000, 3000, 50)]
    before, inside, after, late = 0.5, 1.05, 2.0, 3.5
    assert remap_times([before, inside, after, late], edits, 1000) == [0.5, 1.0, 1.9, 3.45]
    # A tempo of 1.25× makes everything 0.8 as long.
    assert remap_times([2.0], edits, 1000, tempo=1.25) == pytest.approx([1.9 / 1.25])


def test_words_keep_their_order_and_never_run_backwards():
    words = (Word("a", 0.9, 1.2), Word("b", 1.3, 2.0))
    out = remap_words(words, [GapEdit(1000, 1250, 0)], 1000)
    assert [(w.text, w.start, w.end) for w in out] == [("a", 0.9, 1.0), ("b", 1.05, 1.75)]


@needs_ffmpeg
def test_fitting_returns_the_words_at_their_new_times(tmp_path):
    path, natural = two_words(tmp_path)        # words at 0.1–0.6 and 1.0–1.5
    words = (Word("one", 0.1, 0.6), Word("two", 1.0, 1.5))
    _, duration, notes, moved = fit_elastically(path, tmp_path / "fit.wav", 1.35, words=words)
    assert duration == pytest.approx(1.35, abs=0.02)
    # The lead-in gave up a little, the pause between the words most of it.
    assert 0.0 <= moved[0].start <= 0.1 and moved[0].end - moved[0].start == pytest.approx(0.5, abs=0.02)
    assert moved[1].start < 1.0 - 0.1 and moved[1].end < 1.5 - 0.1
    assert moved[0].end <= moved[1].start and moved[1].end <= duration + 0.01


@needs_ffmpeg
def test_place_scales_the_words_for_an_explicit_stretch(tmp_path):
    path, natural = two_words(tmp_path)        # 1.6 s
    words = (Word("one", 0.1, 0.6), Word("two", 1.0, 1.5))
    _, _, _, stretched = place(path, tmp_path / "s.wav", 0.8, fit="stretch", words=words)
    assert stretched[1].start == pytest.approx(0.5, abs=0.01)
    _, _, _, held = place(path, tmp_path / "c.wav", 0.8, mix="concatenate", words=words)
    assert held == words


# ── Phase 16: the picture as a rung ─────────────────────────────────────────────
from app.media import fit  # noqa: E402

def test_a_long_take_flexes_the_picture_before_the_speech_is_sped_up(tmp_path):
    take = tmp_path / "take.wav"
    _write(take, _tone(1.10))
    path, duration, notes, _ = fit.fit_elastically(take, tmp_path / "out.wav", 1.0, flex_max=1.12)
    assert duration == pytest.approx(1.10, abs=0.02)        # the slot stretched to the take
    assert fit.flex_of(notes) == pytest.approx(1.10, abs=0.01)
    assert not any(n.startswith("speech at") for n in notes)


def test_past_the_flex_limit_the_speech_takes_the_rest(tmp_path):
    take = tmp_path / "take.wav"
    _write(take, _tone(1.20))
    path, duration, notes, _ = fit.fit_elastically(take, tmp_path / "out.wav", 1.0, flex_max=1.12)
    assert fit.flex_of(notes) == pytest.approx(1.12, abs=0.001)
    assert duration == pytest.approx(1.12, abs=0.02)
    assert any(n.startswith("speech at 1.07") for n in notes)


def test_a_short_take_speeds_the_picture_a_touch(tmp_path):
    take = tmp_path / "take.wav"
    _write(take, _tone(0.92))
    path, duration, notes, _ = fit.fit_elastically(take, tmp_path / "out.wav", 1.0, flex_max=1.12)
    assert fit.flex_of(notes) == pytest.approx(0.92, abs=0.01)
    assert duration == pytest.approx(0.92, abs=0.02)


def test_without_a_flex_limit_the_picture_is_left_alone(tmp_path):
    take = tmp_path / "take.wav"
    _write(take, _tone(1.10))
    path, duration, notes, _ = fit.fit_elastically(take, tmp_path / "out.wav", 1.0)
    assert fit.flex_of(notes) == 1.0 and duration == pytest.approx(1.0, abs=0.02)
    assert fit.flex_of(["nearest of 3 takes"]) == 1.0
