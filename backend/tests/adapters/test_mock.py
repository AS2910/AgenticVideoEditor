from app.domain.models import Source, Selection, EditPlan
from app.adapters.mock import (
    MockTranscriptionAdapter, MockVoiceAdapter, MockLipSyncAdapter,
)

SOURCE = Source(project_id="p1", filename="ad.mp4", duration=30.0)
PLAN = EditPlan(selection=Selection(0.4, 1.3), new_text="30% off", voice_profile_id="speaker-1")


def test_transcription_returns_words_with_timestamps():
    transcript = MockTranscriptionAdapter().transcribe(SOURCE)
    assert len(transcript.words) > 0
    assert transcript.words[0].start == 0.0
    # timestamps are monotonic
    for earlier, later in zip(transcript.words, transcript.words[1:]):
        assert earlier.end <= later.start


def test_voice_synthesis_is_deterministic_and_text_sensitive():
    voice = MockVoiceAdapter()
    a = voice.synthesize("30% off", "speaker-1")
    b = voice.synthesize("30% off", "speaker-1")
    c = voice.synthesize("40% off", "speaker-1")
    assert a == b            # deterministic
    assert a != c            # different text -> different ref
    assert a.startswith("audio://")


def test_lipsync_returns_frames_ref():
    frames = MockLipSyncAdapter().sync(SOURCE, PLAN, "audio://xyz")
    assert frames.startswith("frames://")


def test_lipsync_is_deterministic_and_input_sensitive():
    lipsync = MockLipSyncAdapter()
    a = lipsync.sync(SOURCE, PLAN, "audio://x")
    b = lipsync.sync(SOURCE, PLAN, "audio://x")
    c = lipsync.sync(SOURCE, PLAN, "audio://y")
    assert a == b
    assert a != c
