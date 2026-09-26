"""Choose real or mock adapters from settings.

The rule is the same for every vendor: a key makes it real, no key falls back
to the mock, and dry-run forces the mock whatever keys exist — so the whole app
can be exercised without spending anything. Each function also returns the
label `/health` reports.
"""
from __future__ import annotations

from app.adapters.claude_intent import MODEL as CLAUDE_MODEL, ClaudeInterpreter
from app.adapters.elevenlabs import ElevenLabsVoiceAdapter
from app.adapters.mock import MockTranscriptionAdapter, MockVoiceAdapter
from app.adapters.openai_whisper import MODEL as WHISPER_MODEL, WhisperTranscriptionAdapter
from app.budget import VoiceBudget
from app.config import Settings
from app.continuity.engine import ContinuityEngine
from app.continuity.measured import MeasuredContinuityEngine
from app.orchestrator.intent import RuleInterpreter
from app.store.artifacts import ArtifactStore


def select_transcriber(settings: Settings):
    if settings.dry_run:
        return MockTranscriptionAdapter(), "dry-run"
    if settings.has_openai:
        return WhisperTranscriptionAdapter(settings.openai_api_key), f"openai:{WHISPER_MODEL}"
    return MockTranscriptionAdapter(), "mock"


def select_voice(settings: Settings, store: ArtifactStore, budget: VoiceBudget):
    if settings.dry_run:
        return MockVoiceAdapter(store), "dry-run"
    if settings.has_elevenlabs:
        adapter = ElevenLabsVoiceAdapter(
            settings.elevenlabs_api_key, store, budget,
            model=settings.elevenlabs_model, voice_id=settings.elevenlabs_voice_id,
        )
        return adapter, f"elevenlabs:{settings.elevenlabs_model}:{adapter.identity}"
    return MockVoiceAdapter(store), "mock"


def select_continuity(voice_identity: str, store: ArtifactStore):
    """Measure continuity whenever the voice is real.

    A mock voice is a sine tone: measuring its "prosody" would only ever say
    "not speech". So a mock voice keeps the mock engine, whose report says
    nothing was measured.
    """
    if voice_identity == "mock":
        return ContinuityEngine(), "mock"
    engine = MeasuredContinuityEngine(store)
    return engine, "measured:" + ",".join(engine.measures)


def select_interpreter(settings: Settings):
    if settings.dry_run:
        return RuleInterpreter(), "dry-run"
    if settings.has_anthropic:
        interpreter = ClaudeInterpreter(settings.anthropic_api_key, settings.anthropic_workspace_id)
        return interpreter, f"anthropic:{CLAUDE_MODEL}"
    return RuleInterpreter(), "rules"
