"""Voice match and naturalness gates of the measured engine (Phase 15d), with fakes."""
import numpy as np
import pytest

from app.continuity import measured as m
from app.domain.models import EditPlan, MediaArtifact, Selection, Transcript, Word
from app.media import ffmpeg
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")

RATE = 24000
PLAN = EditPlan(Selection(1.0, 2.0), "new line", "speaker-1")
WORDS = Transcript(words=(Word("a", 0.5, 1.0), Word("b", 2.0, 2.5)))


def tone(seconds, level=0.1):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


@pytest.fixture()
def scene(store, tmp_path):
    """A 3 s source with speech at 0.5-1.0 and 2.0-2.5, and a 0.6 s take in the same pitch."""
    x = np.zeros(3 * RATE, np.float32)
    for start in (0.5, 2.0):
        i = int(start * RATE)
        x[i:i + RATE // 2] += tone(0.5)
    m._write_wav(tmp_path / "src.wav", x, RATE)
    media = MediaArtifact("audio", "r" * 64, str(tmp_path / "src.wav"), 3.0, "wav")
    m._write_wav(tmp_path / "gen.wav", tone(0.6), RATE)
    take = store.put_file("p1", tmp_path / "gen.wav", kind="audio", container="wav", duration=0.6)
    return make_source(media=media, duration=3.0), take


def assess(store, scene, *, match=None, mos=None, words=WORDS):
    source, take = scene
    engine = m.MeasuredContinuityEngine(store, match=match, mos=mos)
    return engine.assess(source, words, PLAN, take).report


def test_a_take_that_sounds_unlike_the_speaker_fails_with_the_reason(store, scene):
    report = assess(store, scene, match=lambda ref, cand: 0.62)
    assert report.voice_match == 0.62
    assert "Sounds less like the speaker than it should (match 0.62, wants 0.75)." in report.warnings
    assert not report.passed
    assert "voice_match" in report.measured


def test_a_take_that_sounds_like_the_speaker_passes(store, scene):
    report = assess(store, scene, match=lambda ref, cand: 0.82)
    assert report.voice_match == 0.82
    assert not any("speaker" in w for w in report.warnings)
    assert report.passed


def test_the_reference_is_the_speakers_speech_outside_the_selection(store, scene):
    seen = []

    def match(ref, cand):
        seen.append(m._read_wav(str(ref))[0].size / m.signals.RATE)
        return 0.9

    assess(store, scene, match=match)
    assert seen == [pytest.approx(1.0, abs=0.05)]    # two half-second words, none of the selection


def test_an_unmeasurable_match_does_not_block(store, scene):
    report = assess(store, scene, match=lambda ref, cand: None)
    assert report.voice_match is None and report.passed
    assert "voice_match" not in report.measured


def test_low_naturalness_fails_with_the_reason(store, scene):
    report = assess(store, scene, mos=lambda cand: 2.4)
    assert report.naturalness == 2.4
    assert "Sounds less natural than it should (naturalness 2.4, wants 3.0)." in report.warnings
    assert not report.passed


def test_good_or_unmeasured_naturalness_passes(store, scene):
    assert assess(store, scene, mos=lambda cand: 3.8).passed
    unmeasured = assess(store, scene, mos=lambda cand: None)
    assert unmeasured.naturalness is None and unmeasured.passed


def test_naturalness_is_scored_even_without_context(store, scene):
    report = assess(store, scene, mos=lambda cand: 4.1, match=lambda r, c: 0.9, words=Transcript(words=()))
    assert report.naturalness == 4.1
    assert report.voice_match is None    # nothing of the speaker to compare with


def test_measures_list_only_what_is_live(store):
    assert m.MeasuredContinuityEngine(store, match=lambda r, c: 1.0).measures == (
        "prosody", "audio_integration", "voice_match")
    assert m.MeasuredContinuityEngine(store, mos=lambda c: 4.0).measures == (
        "prosody", "audio_integration", "naturalness")
    assert m.MeasuredContinuityEngine(store).measures == ("prosody", "audio_integration")  # AVE_MEASURE=0
