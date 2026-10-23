"""Rehearsal item 2: AVE_MOCK_VENDORS=1 runs the whole app offline, Claude
included, with the waits and charges of the real vendors; never in production."""
from dataclasses import replace

import pytest

from app.adapters import mock_claude
from app.adapters.elevenlabs import VoiceConfigError, VoiceError
from app.adapters.mock_claude import MockAnthropic, seconds_range
from app.adapters.rehearsal import RehearsalVoiceAdapter
from app.adapters.selection import anthropic_client, select_planner, select_transcriber, select_voice
from app.budget import VoiceBudget
from app.chaos import Chaos, parse
from app.config import load_settings, production_problems
from app.store.artifacts import ArtifactStore
from app.usage import Ledger
from app.store.db import Database
from app.domain.models import EditPlan, Selection
from tests.factories import make_source


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    for name in ("AVE_MOCK_CLAUDE_SECONDS", "AVE_MOCK_SYNTH_SECONDS", "AVE_MOCK_RENDER_SECONDS"):
        monkeypatch.setenv(name, "0")


def test_the_mock_vendors_are_chosen_and_refused_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("AVE_MOCK_VENDORS", "1")
    settings = replace(load_settings(), openai_api_key="sk-real", elevenlabs_api_key="xi-real", anthropic_api_key=None)
    assert settings.mock_vendors and settings.has_anthropic
    assert select_transcriber(settings)[1] == "mock:rehearsal"
    budget = VoiceBudget(10_000, Ledger(Database()))
    voice, label = select_voice(settings, ArtifactStore(tmp_path), budget)
    assert label == "mock:rehearsal" and isinstance(voice, RehearsalVoiceAdapter)
    assert isinstance(anthropic_client(settings), MockAnthropic)
    assert select_planner(settings)[1] == "mock:rehearsal"
    assert any("AVE_MOCK_VENDORS" in p for p in production_problems({"AVE_MOCK_VENDORS": "1"}))


def test_mock_claude_proposes_a_placed_line_then_ends_the_turn():
    client = MockAnthropic()
    first = client.beta.messages.create(messages=[{"role": "user", "content": "Make it warmer."}])
    use = next(b for b in first.content if b["type"] == "tool_use")
    assert first.stop_reason == "tool_use" and use["name"] == "synthesize_take"
    assert use["input"]["start"] == 0.5 and use["input"]["mix"] == "layer"     # no clip named: the default span
    sized = client.beta.messages.create(messages=[{"role": "user", "content": [{"type": "text", "text": "The clip: ad.mp4, 2.3 s, one speaker, 1 line."}]}])
    placed = next(b for b in sized.content if b["type"] == "tool_use")["input"]
    assert (placed["start"], placed["end"]) == (0.23, 2.2)
    assert first.usage.input_tokens > 1000
    second = client.beta.messages.create(messages=[{"role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"], "content": "ok"}]}])
    assert second.stop_reason == "end_turn" and "—" not in second.content[0]["text"]
    after_crash = client.beta.messages.create(messages=[{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "old", "content": "interrupted", "is_error": True}, {"type": "text", "text": "Go ahead"}]}])
    assert after_crash.stop_reason == "tool_use"                      # a dead turn's answer plus new words: act on them
    assert client.messages.parse().parsed_output is None          # the planner's reads fall back to plain answers


def test_the_rehearsal_voice_charges_like_the_vendor_and_refunds_a_failure(tmp_path):
    ledger = Ledger(Database())
    budget = VoiceBudget(10_000, ledger, usd_per_1k=0.30)
    voice = RehearsalVoiceAdapter(ArtifactStore(tmp_path), budget, None, takes_per_line=3)
    source = make_source(project_id="p1")
    plan = EditPlan(Selection(0.5, 2.5), "Fresh every morning.", "mock")
    voice.synthesize(source, plan)
    assert budget.spent("p1") == len("Fresh every morning.") * 3
    failing = RehearsalVoiceAdapter(ArtifactStore(tmp_path), budget, Chaos(parse("elevenlabs=status:500")), 3)
    with pytest.raises(VoiceError):
        failing.synthesize(source, plan)
    refused = RehearsalVoiceAdapter(ArtifactStore(tmp_path), budget, Chaos(parse("elevenlabs=status:401")), 3)
    with pytest.raises(VoiceConfigError):
        refused.synthesize(source, plan)
    assert budget.spent("p1") == len("Fresh every morning.") * 3      # both failures gave their charge back


def test_chaos_reaches_the_agents_calls_too():
    import anthropic
    client = Chaos(parse("anthropic=status:500")).anthropic_client(MockAnthropic())
    with pytest.raises(anthropic.InternalServerError):
        client.beta.messages.create(messages=[{"role": "user", "content": "hi"}])


def test_wait_ranges_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("AVE_MOCK_SYNTH_SECONDS", "2-6")
    assert seconds_range("AVE_MOCK_SYNTH_SECONDS", "1") == (2.0, 6.0)
    monkeypatch.setenv("AVE_MOCK_SYNTH_SECONDS", "junk")
    assert seconds_range("AVE_MOCK_SYNTH_SECONDS", "1-3") == (1.0, 3.0)
    assert mock_claude.wait("AVE_MOCK_RENDER_SECONDS", "0") == 0.0
