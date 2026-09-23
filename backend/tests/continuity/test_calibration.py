"""The labelled set the measured thresholds were chosen against (spec §9).

Built from the bundled sample ad, so it runs offline. *Good* edits are the
speaker's own original line and the real ElevenLabs "30% off" (the fixture);
*bad* edits are the original line pitch-shifted ±6 semitones or drowned in
noise. Every good edit must pass and every bad one must fail — this is Phase
6a's exit criterion "a deliberately bad edit reliably fails", pinned.
"""
from pathlib import Path

import numpy as np
import pytest

from app.continuity import signals
from app.continuity.measured import MeasuredContinuityEngine
from app.domain.models import EditPlan, MediaArtifact, Selection, Transcript, Word
from app.media import ffmpeg
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")

ROOT = Path(__file__).parents[2]
SAMPLE = ROOT.parent / "frontend" / "public" / "sample-ad.mp4"
FIXTURE_PCM = ROOT / "tests" / "fixtures" / "elevenlabs-tts.pcm"

# Word timings Whisper returned for the sample ad (live, 2026-09-23).
WORDS = Transcript(words=(
    Word("Get", 0.0, 0.24), Word("20", 0.24, 0.56), Word("off", 0.96, 1.2),
    Word("today", 1.2, 1.46), Word("only", 1.46, 1.82),
))
PLAN = EditPlan(Selection(0.24, 1.2), "30% off", "speaker-1")
SPAN = PLAN.selection.end - PLAN.selection.start
RATE = 24000


@pytest.fixture(scope="module")
def source():
    duration = ffmpeg.duration_of(SAMPLE)
    media = MediaArtifact("video", "s" * 64, str(SAMPLE), duration, "mp4")
    return make_source(media=media, duration=duration)


def stored(store, path) -> MediaArtifact:
    return store.put_file("p1", path, kind="audio", container="wav", duration=ffmpeg.duration_of(path))


def original_line(tmp_path):
    path, _ = ffmpeg.extract_segment(SAMPLE, tmp_path / "orig.wav", 0.24, 1.2, sample_rate=RATE)
    return path


def pitch_shifted(tmp_path, st):
    factor = 2 ** (st / 12)
    dest = tmp_path / f"shift{st}.wav"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(original_line(tmp_path)),
        "-af", f"asetrate={RATE * factor:.0f},aresample={RATE},atempo={1 / factor:.6f}",
        "-ac", "1", "-c:a", "pcm_s16le", str(dest),
    ])
    return dest


def noisy(tmp_path):
    x = signals.load(original_line(tmp_path), rate=RATE)
    x = x + np.random.default_rng(0).standard_normal(x.size).astype(np.float32) * 0.05
    from app.continuity.measured import _write_wav
    _write_wav(tmp_path / "noisy.wav", x, RATE)
    return tmp_path / "noisy.wav"


def elevenlabs(tmp_path):
    raw, _ = ffmpeg.pcm_to_wav(FIXTURE_PCM.read_bytes(), tmp_path / "raw.wav", RATE)
    path, _ = ffmpeg.fit_duration(raw, tmp_path / "eleven.wav", SPAN)
    return path


GOOD = {"the speaker's own line": original_line, "ElevenLabs stock voice": elevenlabs}
BAD = {
    "pitched up 6 semitones": lambda p: pitch_shifted(p, 6),
    "pitched down 6 semitones": lambda p: pitch_shifted(p, -6),
    "drowned in noise": noisy,
}


def assess(store, source, path):
    return MeasuredContinuityEngine(store).assess(source, WORDS, PLAN, stored(store, path))


@pytest.mark.parametrize("name", GOOD)
def test_good_edits_pass(store, source, tmp_path, name):
    report = assess(store, source, GOOD[name](tmp_path)).report
    assert report.passed, (name, report)
    assert report.measured == ("prosody", "audio_integration")


@pytest.mark.parametrize("name", BAD)
def test_bad_edits_fail(store, source, tmp_path, name):
    report = assess(store, source, BAD[name](tmp_path)).report
    assert not report.passed, (name, report)
    assert report.warnings  # and say why


def test_pitch_failures_are_explained_in_semitones(store, source, tmp_path):
    report = assess(store, source, pitch_shifted(tmp_path, 6)).report
    assert any("semitones" in w for w in report.warnings)


def test_a_loud_line_is_corrected_to_the_context_level(store, source, tmp_path):
    x = signals.load(original_line(tmp_path), rate=RATE) * 3.0  # +9.5 dB
    from app.continuity.measured import _write_wav
    _write_wav(tmp_path / "loud.wav", x, RATE)
    result = assess(store, source, tmp_path / "loud.wav")

    context = np.concatenate([signals.load(SAMPLE, 0.0, 0.24), signals.load(SAMPLE, 1.2, 1.82)])
    corrected = signals.speech_level_db(signals.load(result.audio.path))
    assert corrected == pytest.approx(signals.speech_level_db(context), abs=1.0)
    assert result.report.passed
    assert result.audio.duration == pytest.approx(SPAN, abs=0.01)


def test_voice_and_lip_sync_are_not_measured(store, source, tmp_path):
    report = assess(store, source, original_line(tmp_path)).report
    assert report.voice_match is None and report.lip_sync is None
