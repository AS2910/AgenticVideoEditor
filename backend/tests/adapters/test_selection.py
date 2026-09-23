"""Which adapter a process runs with, given its settings. No network."""
from pathlib import Path

from app.adapters.elevenlabs import ElevenLabsVoiceAdapter
from app.adapters.mock import MockVoiceAdapter, MockTranscriptionAdapter
from app.adapters.openai_whisper import WhisperTranscriptionAdapter
from app.adapters.selection import select_continuity, select_voice, select_transcriber
from app.continuity.engine import ContinuityEngine
from app.continuity.measured import MeasuredContinuityEngine
from app.budget import VoiceBudget
from app.config import Settings


def settings(**overrides) -> Settings:
    base = dict(openai_api_key=None, data_dir=Path("/tmp/unused"))
    return Settings(**{**base, **overrides})


def voice_for(store, **overrides):
    return select_voice(settings(**overrides), store, VoiceBudget(ceiling=10))


def test_no_key_means_the_mock_voice(store):
    adapter, label = voice_for(store)
    assert isinstance(adapter, MockVoiceAdapter)
    assert label == "mock"


def test_a_key_means_elevenlabs_labelled_with_its_model(store):
    adapter, label = voice_for(store, elevenlabs_api_key="sk_x", elevenlabs_model="eleven_flash_v2_5")
    assert isinstance(adapter, ElevenLabsVoiceAdapter)
    assert label == "elevenlabs:eleven_flash_v2_5:stock"


def test_dry_run_wins_over_a_key(store):
    adapter, label = voice_for(store, elevenlabs_api_key="sk_x", dry_run=True)
    assert isinstance(adapter, MockVoiceAdapter)
    assert label == "dry-run"


def test_transcription_follows_the_same_rules():
    assert isinstance(select_transcriber(settings())[0], MockTranscriptionAdapter)
    live, label = select_transcriber(settings(openai_api_key="sk-x"))
    assert isinstance(live, WhisperTranscriptionAdapter) and label == "openai:whisper-1"
    dry, label = select_transcriber(settings(openai_api_key="sk-x", dry_run=True))
    assert isinstance(dry, MockTranscriptionAdapter) and label == "dry-run"


def test_a_real_voice_gets_measured_continuity(store):
    engine, label = select_continuity("stock", store)
    assert isinstance(engine, MeasuredContinuityEngine)
    assert label == "measured:prosody,audio_integration"


def test_a_mock_voice_keeps_the_mock_engine(store):
    engine, label = select_continuity("mock", store)
    assert isinstance(engine, ContinuityEngine)
    assert label == "mock"
