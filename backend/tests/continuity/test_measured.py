"""Scoring and context rules of the measured engine."""
import numpy as np
import pytest

from app.continuity import measured as m
from app.continuity import signals
from app.domain.models import Selection, Transcript, Word

WORDS = Transcript(words=(
    Word("Get", 0.0, 0.24), Word("20", 0.24, 0.56), Word("off", 0.96, 1.2),
    Word("today", 1.2, 1.46), Word("only", 1.46, 1.82),
))
SELECTION = Selection(0.24, 1.2)


def test_identical_pitch_scores_one_and_falls_off_with_distance():
    assert m.pitch_score(220, 220) == 1.0
    scores = [m.pitch_score(220 * 2 ** (st / 12), 220) for st in (1, 2, 4, 8)]
    assert scores == sorted(scores, reverse=True)
    assert m.pitch_score(220 * 2 ** (4 / 12), 220) == pytest.approx(0.8)


def test_pitch_score_is_symmetric():
    up, down = m.pitch_score(220 * 2 ** (3 / 12), 220), m.pitch_score(220 / 2 ** (3 / 12), 220)
    assert up == pytest.approx(down)


def test_unmeasurable_inputs_give_none_not_a_guess():
    assert m.pitch_score(None, 220) is None
    assert m.level_score(None) is None
    assert m.clarity_score(None, 30) is None


def test_level_tolerance_is_3_db():
    assert m.level_score(0) == 1.0
    assert m.level_score(3) == pytest.approx(0.8)
    assert m.level_score(-3) == pytest.approx(0.8)


def test_only_a_less_clear_line_is_penalised():
    assert m.clarity_score(40, 25) == 1.0     # cleaner than the room: fine
    assert m.clarity_score(19, 25) == pytest.approx(0.8)


def test_context_is_the_words_either_side_never_the_selection():
    spans = m.context_spans(WORDS, SELECTION)
    assert spans == [(0.0, 0.24), (1.2, 1.82)]
    for start, end in spans:
        assert end <= SELECTION.start or start >= SELECTION.end


def test_context_is_limited_to_the_window():
    far = Transcript(words=(Word("far", 0.0, 0.5), Word("near", 9.0, 9.5), Word("x", 10.0, 10.5)))
    assert m.context_spans(far, Selection(10.0, 10.5), window=3.0) == [(9.0, 9.5)]


def test_no_words_outside_the_selection_means_no_context():
    assert m.context_spans(WORDS, Selection(0.0, 1.82)) == []


def test_gaps_are_the_stretches_with_no_words():
    words = Transcript(words=(Word("a", 0.5, 1.0), Word("b", 1.05, 1.5)))
    # 0.00-0.50 (edge), 1.00-1.05 (too short), 1.50-3.00 (edge), each trimmed 0.05.
    assert m.gap_spans(words, 3.0) == [(0.05, 0.45), (1.55, 2.95)]


def test_clarity_is_speech_above_the_quiet_part():
    rng = np.random.default_rng(0)
    t = np.arange(signals.RATE) / signals.RATE
    speech = 0.1 * np.sin(2 * np.pi * 200 * t)
    quiet = rng.standard_normal(signals.RATE) * 0.001
    x = np.concatenate([quiet, speech, quiet]).astype(np.float32)
    assert m.clarity(x) == pytest.approx(40, abs=4)  # -23 dB speech over -60 dB floor


def test_quiet_part_drops_speech_hiding_in_a_gap():
    rate = 16000
    t = np.arange(rate) / rate
    room = np.random.default_rng(0).standard_normal(rate).astype(np.float32) * 0.001  # ~-60 dB
    speech = (0.1 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)                    # ~-23 dB
    kept = m.quiet_part(np.concatenate([room, speech]), rate, below_db=-45)
    assert kept.size == pytest.approx(rate, rel=0.02)          # all the room, none of the speech
    assert np.sqrt(np.mean(kept ** 2)) < 0.002


# ── auto-correction on synthetic media ───────────────────────────────────────

from app.domain.models import EditPlan, MediaArtifact  # noqa: E402
from app.media import ffmpeg  # noqa: E402
from tests.factories import make_source  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
RATE = 24000


def _tone(seconds, level=0.1):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def _room_source(tmp_path, room_level):
    """3 s: a room at `room_level` RMS, with 'words' (tones) at 0.5-1.0 and 2.0-2.5."""
    x = np.random.default_rng(0).standard_normal(3 * RATE).astype(np.float32) * room_level
    for start in (0.5, 2.0):
        i = int(start * RATE)
        x[i:i + RATE // 2] += _tone(0.5)
    m._write_wav(tmp_path / "src.wav", x, RATE)
    media = MediaArtifact("audio", "r" * 64, str(tmp_path / "src.wav"), 3.0, "wav")
    words = Transcript(words=(Word("a", 0.5, 1.0), Word("b", 2.0, 2.5)))
    return make_source(media=media, duration=3.0), words


def _studio_line(tmp_path, store):
    """0.3 s of speech then 0.3 s of digital silence — a clean TTS line."""
    m._write_wav(tmp_path / "gen.wav", np.concatenate([_tone(0.3), np.zeros(int(0.3 * RATE), np.float32)]), RATE)
    return store.put_file("p1", tmp_path / "gen.wav", kind="audio", container="wav", duration=0.6)


def _tail_level_db(path):
    x, _ = m._read_wav(path)
    tail = x[int(0.35 * RATE):]
    return 20 * np.log10(max(float(np.sqrt(np.mean(tail ** 2))), 1e-10))


@needs_ffmpeg
def test_room_tone_fills_studio_silence_when_the_room_is_audible(store, tmp_path):
    source, words = _room_source(tmp_path, room_level=0.003)          # ~-50 dB room
    plan = EditPlan(Selection(1.2, 1.8), "new", "speaker-1")
    result = m.MeasuredContinuityEngine(store).assess(source, words, plan, _studio_line(tmp_path, store))
    assert _tail_level_db(result.audio.path) == pytest.approx(-50, abs=3)


@needs_ffmpeg
def test_a_silent_room_adds_nothing(store, tmp_path):
    source, words = _room_source(tmp_path, room_level=0.0)
    plan = EditPlan(Selection(1.2, 1.8), "new", "speaker-1")
    result = m.MeasuredContinuityEngine(store).assess(source, words, plan, _studio_line(tmp_path, store))
    assert _tail_level_db(result.audio.path) < -90


@needs_ffmpeg
def test_no_context_means_no_scores_and_no_room_tone(store, tmp_path):
    source, words = _room_source(tmp_path, room_level=0.003)
    plan = EditPlan(Selection(0.0, 3.0), "new", "speaker-1")   # covers every word
    result = m.MeasuredContinuityEngine(store).assess(source, words, plan, _studio_line(tmp_path, store))
    assert result.report.measured == ()
    assert result.report.passed is True
    assert any("Not enough surrounding speech" in w for w in result.report.warnings)
    assert _tail_level_db(result.audio.path) < -90


@needs_ffmpeg
def test_a_missing_transcript_is_treated_as_no_context(store, tmp_path):
    source, _ = _room_source(tmp_path, room_level=0.003)
    plan = EditPlan(Selection(1.2, 1.8), "new", "speaker-1")
    result = m.MeasuredContinuityEngine(store).assess(source, None, plan, _studio_line(tmp_path, store))
    assert result.report.measured == ()
