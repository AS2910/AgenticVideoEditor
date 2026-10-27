"""Run 5 item 7 in the measured engine: delivery refused, measured, and the room on the take."""
import numpy as np
import pytest

from app.continuity import measured as m
from app.continuity import signals
from app.domain.models import EditPlan, MediaArtifact, Selection, Transcript, Word
from app.media import ffmpeg
from tests.continuity.test_prosody import speech
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")

LINES = ((0.5, 1.5), (2.0, 3.0), (5.0, 6.0), (6.5, 7.5))   # the speaker's lines; the edit is 3.5-4.5
SELECTION = Selection(3.5, 4.5)


def _source(tmp_path, floor=0.0003):
    x = (np.random.default_rng(0).standard_normal(8 * signals.RATE) * floor).astype(np.float32)
    for i, (a, b) in enumerate(LINES + ((3.5, 4.5),)):
        line = speech(b - a, f0=(150, 260) if i % 2 == 0 else (250, 150), syllables=4.0)
        x[int(a * signals.RATE):int(a * signals.RATE) + line.size] += line
    m._write_wav(tmp_path / "src.wav", x, signals.RATE)
    media = MediaArtifact("audio", "s" * 64, str(tmp_path / "src.wav"), 8.0, "wav")
    words = []
    for a, b in LINES + ((3.5, 4.5),):
        words += [Word("la", a, (a + b) / 2, "A"), Word("la", (a + b) / 2 + 0.05, b, "A")]
    return make_source(media=media, duration=8.0), Transcript(words=tuple(words))


def _take(tmp_path, store, x, name="take"):
    m._write_wav(tmp_path / f"{name}.wav", x, signals.RATE)
    return store.put_file("p1", tmp_path / f"{name}.wav", kind="audio", container="wav", duration=x.size / signals.RATE)


def test_a_flat_rushed_take_is_refused_with_the_reason(store, tmp_path):
    source, words = _source(tmp_path)
    take = _take(tmp_path, store, speech(1.0, f0=(200, 202), syllables=9.0))
    result = m.MeasuredContinuityEngine(store, tone=True).assess(source, words, EditPlan(SELECTION, "new", "v"), take)
    assert not result.report.passed
    assert any(w.startswith("Flatter than the lines") for w in result.report.warnings)
    assert result.delivery is not None and result.delivery.flatter > 1
    assert result.report.prosody_distance is not None and "prosody_distance" in result.report.measured


def test_a_take_like_the_speaker_passes_and_is_close(store, tmp_path):
    source, words = _source(tmp_path)
    take = _take(tmp_path, store, speech(1.0, f0=(150, 260), syllables=4.0))
    result = m.MeasuredContinuityEngine(store, tone=True).assess(source, words, EditPlan(SELECTION, "new", "v"), take)
    assert not any(w.startswith(("Flatter", "Said", "More sing-song", "Pitched")) for w in result.report.warnings)
    assert result.report.prosody_distance < 1.0


def test_a_directed_line_is_measured_but_not_refused(store, tmp_path):
    source, words = _source(tmp_path)
    take = _take(tmp_path, store, speech(1.0, f0=(200, 202), syllables=9.0))
    for plan in (EditPlan(SELECTION, "new", "v", delivery="calmer"),
                 EditPlan(SELECTION, "new", "v", voice_settings={"stability": 0.9})):
        result = m.MeasuredContinuityEngine(store, tone=True).assess(source, words, plan, take)
        assert not any(w.startswith("Flatter") for w in result.report.warnings)
        assert result.report.prosody_distance is not None


def test_tone_off_is_the_engine_as_before(store, tmp_path):
    source, words = _source(tmp_path)
    take = _take(tmp_path, store, speech(1.0, f0=(200, 202), syllables=9.0))
    result = m.MeasuredContinuityEngine(store, tone=False).assess(source, words, EditPlan(SELECTION, "new", "v"), take)
    assert result.report.prosody_distance is None and result.delivery is None and not result.roomed
    assert not any(w.startswith("Flatter") for w in result.report.warnings)


def test_a_clean_room_is_put_on_the_take_and_a_noisy_one_is_left_to_the_render(store, tmp_path):
    take_x = speech(1.0, f0=(150, 260))
    clean, words = _source(tmp_path)
    engine = m.MeasuredContinuityEngine(store, tone=True)
    plan = EditPlan(SELECTION, "new", "v")
    roomed = engine.assess(clean, words, plan, _take(tmp_path, store, take_x))
    assert roomed.roomed
    # Same length, same level: the room changes the colour, not the loudness.
    out = signals.load(roomed.audio.path)
    assert out.size == pytest.approx(take_x.size, abs=200)
    (tmp_path / "n").mkdir()
    noisy, words = _source(tmp_path / "n", floor=0.03)
    left = engine.assess(noisy, words, plan, _take(tmp_path, store, take_x, "take2"))
    assert not left.roomed


def test_the_first_take_reference_is_off_unless_asked_for(store, tmp_path, monkeypatch):
    source, words = _source(tmp_path)
    monkeypatch.delenv("AVE_VOICE_TONE_REFERENCE", raising=False)
    assert m.MeasuredContinuityEngine(store, tone=True).reference(source, words, EditPlan(SELECTION, "new", "v")) is None
    monkeypatch.setenv("AVE_VOICE_TONE_REFERENCE", "1")
    assert m.MeasuredContinuityEngine(store, tone=True).reference(source, words, EditPlan(SELECTION, "new", "v")) is not None


def test_the_first_take_reference_follows_an_animated_speaker(store, tmp_path):
    source, words = _source(tmp_path)
    engine = m.MeasuredContinuityEngine(store, tone=True, reference=True)
    settings = engine.reference(source, words, EditPlan(SELECTION, "new", "v"))
    assert settings is not None and settings["stability"] < 0.5
    assert engine.reference(source, words, EditPlan(SELECTION, "new", "v", delivery="warmer")) is None
    assert engine.reference(source, words, EditPlan(SELECTION, "new", "v", mix="layer")) is None
    assert m.MeasuredContinuityEngine(store, tone=False).reference(source, words, EditPlan(SELECTION, "new", "v")) is None
