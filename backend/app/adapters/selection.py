"""Choose real or mock adapters from settings.

The rule is the same for every vendor: a key makes it real, no key falls back
to the mock, and dry-run forces the mock whatever keys exist — so the whole app
can be exercised without spending anything. Each function also returns the
label `/health` reports.
"""
from __future__ import annotations

from app.adapters.claude_planner import MODEL as CLAUDE_MODEL, ClaudePlanner
from app.adapters.elevenlabs import ElevenLabsVoiceAdapter
from app.adapters.mock import MockTranscriptionAdapter, MockVoiceAdapter
from app.adapters.openai_whisper import MODEL as WHISPER_MODEL, WhisperTranscriptionAdapter
from app.budget import VoiceBudget
from app.config import Settings
from app.continuity.engine import ContinuityEngine
from app.continuity.measured import MeasuredContinuityEngine
from app.store.artifacts import ArtifactStore
from app.chaos import Chaos


def select_transcriber(settings: Settings, chaos: Chaos | None = None):
    if settings.mock_vendors:
        return MockTranscriptionAdapter(), "mock:rehearsal"
    if settings.dry_run:
        return MockTranscriptionAdapter(), "dry-run"
    if settings.has_openai:
        from app.adapters import openai_whisper
        post = chaos.openai_post(openai_whisper._post) if chaos else openai_whisper._post
        return WhisperTranscriptionAdapter(settings.openai_api_key, post=post), f"openai:{WHISPER_MODEL}"
    return MockTranscriptionAdapter(_known_transcripts()), "mock"


def _known_transcripts() -> dict | None:
    """AVE_KNOWN_TRANSCRIPTS: a JSON file of clips whose words are known (the
    cost evals), read by the mock transcriber. Unset in every real deployment."""
    import json
    import os
    from pathlib import Path
    path = (os.environ.get("AVE_KNOWN_TRANSCRIPTS") or "").strip()
    return json.loads(Path(path).read_text()) if path else None


def select_voice(settings: Settings, store: ArtifactStore, budget: VoiceBudget, chaos: Chaos | None = None):
    if settings.mock_vendors:
        from app.adapters.rehearsal import RehearsalVoiceAdapter
        return RehearsalVoiceAdapter(store, budget, chaos, settings.takes_per_line), "mock:rehearsal"
    if settings.dry_run:
        return MockVoiceAdapter(store), "dry-run"
    if settings.has_elevenlabs:
        from app.adapters import elevenlabs
        post = chaos.elevenlabs_post(elevenlabs._post) if chaos else elevenlabs._post
        adapter = ElevenLabsVoiceAdapter(
            settings.elevenlabs_api_key, store, budget,
            model=settings.elevenlabs_model, voice_id=settings.elevenlabs_voice_id,
            takes_per_line=settings.takes_per_line, fit_tolerance=settings.fit_tolerance,
            flex_max=settings.max_flex, post=post,
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


def anthropic_client(settings: Settings, chaos: Chaos | None = None):
    """One Anthropic client for the planner and the interpreter: a 60 s timeout
    and at most two retries of the SDK's own (launch item 4), instead of the
    SDK's ten-minute default that let a hung call hold a worker (the chaos
    pass); wrapped by chaos when faults are on."""
    if settings.mock_vendors:
        from app.adapters.mock_claude import MockAnthropic
        client = MockAnthropic()
        return chaos.anthropic_client(client) if chaos else client
    import anthropic
    headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, default_headers=headers,
                                 timeout=ANTHROPIC_TIMEOUT, max_retries=2)
    return chaos.anthropic_client(client) if chaos else client


ANTHROPIC_TIMEOUT = 60.0


def select_planner(settings: Settings, chaos: Chaos | None = None):
    """Voltage's reads outside the loop (look, read, shorten): Claude, or
    nothing — there is no offline stand-in; without a key the routes that
    need it say so (20d: no non-agentic behaviour)."""
    if settings.has_anthropic and not settings.dry_run:
        planner = ClaudePlanner(settings.anthropic_api_key or "mock", settings.anthropic_workspace_id,
                                client=anthropic_client(settings, chaos))
        return planner, "mock:rehearsal" if settings.mock_vendors else f"anthropic:{CLAUDE_MODEL}"
    return None, "none"
