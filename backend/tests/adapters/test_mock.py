from pathlib import Path

import pytest

from app.domain.models import Selection, EditPlan
from tests.factories import make_source
from app.media import ffmpeg
from app.adapters.mock import (
    MockTranscriptionAdapter, MockVoiceAdapter, MockLipSyncAdapter,
)

SOURCE = make_source()
PLAN = EditPlan(selection=Selection(0.4, 1.3), new_text="30% off", voice_profile_id="speaker-1")


def plan_with(new_text="30% off", voice="speaker-1", span=(0.4, 1.3)) -> EditPlan:
    return EditPlan(Selection(*span), new_text, voice)


def test_transcription_returns_words_with_timestamps():
    transcript = MockTranscriptionAdapter().transcribe(SOURCE)
    assert len(transcript.words) > 0
    assert transcript.words[0].start == 0.0
    # timestamps are monotonic
    for earlier, later in zip(transcript.words, transcript.words[1:]):
        assert earlier.end <= later.start


requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@requires_ffmpeg
def test_voice_synthesis_produces_real_audio_spanning_the_selection(store):
    artifact = MockVoiceAdapter(store).synthesize(SOURCE, PLAN)

    assert artifact.kind == "audio" and artifact.container == "wav"
    assert Path(artifact.path).is_file()
    # The sound is fake; the timing is not — it matches the selected span.
    assert artifact.duration == pytest.approx(0.9, abs=0.05)
    assert ffmpeg.probe(artifact.path)["streams"][0]["codec_name"] == "pcm_s16le"


@requires_ffmpeg
def test_voice_synthesis_is_deterministic_and_text_sensitive(store):
    voice = MockVoiceAdapter(store)
    a = voice.synthesize(SOURCE, plan_with(new_text="30% off"))
    b = voice.synthesize(SOURCE, plan_with(new_text="30% off"))
    c = voice.synthesize(SOURCE, plan_with(new_text="40% off"))

    assert a == b            # deterministic — identical bytes, one file
    assert a.sha256 != c.sha256  # different text -> different media


@requires_ffmpeg
def test_voice_synthesis_is_voice_profile_sensitive(store):
    voice = MockVoiceAdapter(store)
    a = voice.synthesize(SOURCE, plan_with(voice="speaker-1"))
    b = voice.synthesize(SOURCE, plan_with(voice="speaker-2"))
    assert a.sha256 != b.sha256


@requires_ffmpeg
def test_lipsync_produces_real_video_spanning_the_selection(store):
    audio = MockVoiceAdapter(store).synthesize(SOURCE, PLAN)
    frames = MockLipSyncAdapter(store).sync(SOURCE, PLAN, audio)

    assert frames.kind == "video" and frames.container == "mp4"
    assert Path(frames.path).is_file()
    assert frames.duration == pytest.approx(0.9, abs=0.05)
    assert ffmpeg.probe(frames.path)["streams"][0]["codec_name"] == "h264"


@requires_ffmpeg
def test_lipsync_is_deterministic_and_input_sensitive(store):
    voice, lipsync = MockVoiceAdapter(store), MockLipSyncAdapter(store)
    audio_a = voice.synthesize(SOURCE, plan_with(new_text="30% off"))
    audio_b = voice.synthesize(SOURCE, plan_with(new_text="40% off"))

    a = lipsync.sync(SOURCE, PLAN, audio_a)
    b = lipsync.sync(SOURCE, PLAN, audio_a)
    c = lipsync.sync(SOURCE, PLAN, audio_b)

    assert a == b
    assert a.sha256 != c.sha256  # different audio -> different frames


@requires_ffmpeg
def test_degenerate_selection_still_encodes(store):
    # A zero-length drag must not hand ffmpeg a 0s duration and blow up.
    artifact = MockVoiceAdapter(store).synthesize(SOURCE, plan_with(span=(1.0, 1.0)))
    assert Path(artifact.path).is_file()
    assert artifact.duration > 0
