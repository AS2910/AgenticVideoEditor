"""ElevenLabs voice adapter tests. No network, no spend.

Synthesis replays `tests/fixtures/elevenlabs-tts.pcm`, a response genuinely
recorded from eleven_multilingual_v2 saying "30% off" (see the `.json` sidecar),
so the bytes being wrapped and stretched are the bytes the vendor really sends.
"""
import json
from pathlib import Path

import httpx
import pytest

from app.adapters.base import VendorError
from app.adapters.elevenlabs import (
    ElevenLabsVoiceAdapter, VoiceConfigError, billed_characters, to_request,
    SAMPLE_RATE, _post,
)
from app.budget import VoiceBudget, BudgetExceeded
from app.domain.models import EditPlan, Selection, Transcript, Word
from app.errors import NonRetryableError
from app.media import ffmpeg
from tests.factories import make_source

FIXTURES = Path(__file__).parents[1] / "fixtures"
PCM = (FIXTURES / "elevenlabs-tts.pcm").read_bytes()
RECORDED = json.loads((FIXTURES / "elevenlabs-tts.json").read_text())

SOURCE = make_source()
KEY = "sk_test_never_real_0123456789"
TRANSCRIPT = Transcript(words=(
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
    Word("only", 1.8, 2.3),
))
PLAN = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


class FakePost:
    """Stands in for the HTTP call; records what it was asked."""

    def __init__(self, status: int = 200, content: bytes = PCM, text: str = ""):
        self.status, self.content, self.text = status, content, text
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, voice_id, body, api_key, timeout):
        self.calls.append((voice_id, body))
        return self.status, self.content, self.text


def adapter(store, post=None, budget=None, model="eleven_multilingual_v2"):
    return ElevenLabsVoiceAdapter(
        KEY, store, budget or VoiceBudget(ceiling=1000),
        model=model, voice_id="voice-x", post=post or FakePost(),
    )


# --- request shape -----------------------------------------------------------

def test_request_matches_the_one_that_was_recorded():
    # The spike's context was typed by hand with a trailing period; the
    # transcript carries none, which the vendor accepts either way.
    body = to_request(PLAN, TRANSCRIPT, model="eleven_multilingual_v2")
    assert body == {**RECORDED["request"], "next_text": "today only"}


def test_context_is_the_words_either_side_of_the_selection():
    plan = EditPlan(Selection(0.9, 1.3), "cheap", "speaker-1")
    body = to_request(plan, TRANSCRIPT, model="m")
    assert body["previous_text"] == "Get 20%"
    assert body["next_text"] == "today only"


def test_context_is_omitted_at_the_edges():
    plan = EditPlan(Selection(0.0, 2.3), "Buy now", "speaker-1")
    body = to_request(plan, TRANSCRIPT, model="m")
    assert "previous_text" not in body and "next_text" not in body


def test_context_is_capped_on_a_word_boundary():
    long = Transcript(words=tuple(Word(f"word{i}", i, i + 0.5) for i in range(100)))
    plan = EditPlan(Selection(99.0, 99.5), "end", "speaker-1")
    before = to_request(plan, long, model="m")["previous_text"]
    assert len(before) <= 200
    assert before.split()[-1] == "word98"
    assert before.split()[0].startswith("word")  # no half-word at the cut


def test_no_transcript_means_no_context():
    body = to_request(PLAN, None, model="m")
    assert body == {"text": "30% off", "model_id": "m"}


# --- billing -----------------------------------------------------------------

def test_billing_matches_what_the_vendor_charged_in_the_spike():
    # character-cost header: 7 on multilingual_v2, 4 on flash_v2_5.
    assert billed_characters("30% off", "eleven_multilingual_v2") == 7
    assert billed_characters("30% off", "eleven_flash_v2_5") == 4


@needs_ffmpeg
def test_the_budget_is_charged_before_the_call(store):
    budget = VoiceBudget(ceiling=1000)
    seen = []

    def post(voice_id, body, api_key, timeout):
        seen.append(budget.spent("p1"))
        return 200, PCM, ""

    adapter(store, post=post, budget=budget).synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert seen == [7]


def test_an_unaffordable_edit_never_reaches_the_vendor(store):
    post = FakePost()
    with pytest.raises(BudgetExceeded):
        adapter(store, post=post, budget=VoiceBudget(ceiling=3)).synthesize(
            SOURCE, PLAN, TRANSCRIPT,
        )
    assert post.calls == []


# --- synthesis ---------------------------------------------------------------

@needs_ffmpeg
def test_the_recorded_response_becomes_a_stored_wav_fitted_to_the_span(store):
    artifact = adapter(store).synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert artifact.kind == "audio" and artifact.container == "wav"
    assert Path(artifact.path).is_file()
    assert artifact.duration == pytest.approx(0.9, rel=0.05)
    stream = ffmpeg.probe(artifact.path)["streams"][0]
    assert int(stream["sample_rate"]) == SAMPLE_RATE and stream["channels"] == 1


@needs_ffmpeg
def test_the_configured_voice_and_model_are_used(store):
    post = FakePost()
    adapter(store, post=post, model="eleven_flash_v2_5").synthesize(SOURCE, PLAN, TRANSCRIPT)
    voice_id, body = post.calls[0]
    assert voice_id == "voice-x"
    assert body["model_id"] == "eleven_flash_v2_5"


@needs_ffmpeg
def test_a_selection_the_line_cannot_fit_is_refused_without_retry(store):
    tiny = EditPlan(Selection(0.4, 0.5), "30% off", "speaker-1")
    with pytest.raises(ffmpeg.SpanMismatch):
        adapter(store).synthesize(SOURCE, tiny, TRANSCRIPT)


def test_identity_is_stock():
    assert ElevenLabsVoiceAdapter.identity == "stock"


# --- failures ----------------------------------------------------------------

@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transient_failures_are_retryable(store, status):
    with pytest.raises(VendorError) as err:
        adapter(store, post=FakePost(status=status, content=b"", text="busy")).synthesize(
            SOURCE, PLAN, TRANSCRIPT,
        )
    assert not isinstance(err.value, NonRetryableError)


@pytest.mark.parametrize("status,text,phrase", [
    (401, '{"detail":{"status":"invalid_api_key"}}', "API key"),
    (401, '{"detail":{"status":"quota_exceeded"}}', "quota"),
    (403, '{"detail":{"status":"missing_permissions"}}', "API key"),
    (400, '{"detail":{"message":"bad voice"}}', "bad voice"),
    (422, '{"detail":[{"msg":"text too long"}]}', "422"),
])
def test_configuration_failures_are_not_retried(store, status, text, phrase):
    with pytest.raises(VoiceConfigError) as err:
        adapter(store, post=FakePost(status=status, content=b"", text=text)).synthesize(
            SOURCE, PLAN, TRANSCRIPT,
        )
    assert isinstance(err.value, NonRetryableError)
    assert phrase in str(err.value)


def test_a_network_failure_is_retryable(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(VendorError):
        _post("voice-x", {"text": "hi"}, KEY, 1.0)


def test_the_key_never_leaks_into_an_error(store, monkeypatch):
    for status in (401, 500):
        with pytest.raises(Exception) as err:
            adapter(store, post=FakePost(status=status, content=b"", text=f"echo {KEY}")).synthesize(
                SOURCE, PLAN, TRANSCRIPT,
            )
        assert KEY not in str(err.value)

    def boom(*args, **kwargs):
        raise httpx.ConnectError(f"failed with {KEY}")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(VendorError) as err:
        _post("voice-x", {"text": "hi"}, KEY, 1.0)
    assert KEY not in str(err.value)


def test_cost_of_is_the_billed_characters_for_the_new_line(store):
    assert adapter(store).cost_of(PLAN) == 7
    assert adapter(store, model="eleven_flash_v2_5").cost_of(PLAN) == 4


# --- Phase 8: placement, and the take held for a question --------------------

@needs_ffmpeg
def test_a_take_that_did_not_fit_is_reused_when_the_user_answers(store):
    from dataclasses import replace
    post = FakePost()
    budget = VoiceBudget(ceiling=1000)
    voice = adapter(store, post=post, budget=budget)
    wide = EditPlan(Selection(0.0, 3.87), "30% off", "speaker-1")
    with pytest.raises(ffmpeg.SpanMismatch):
        voice.synthesize(SOURCE, wide, TRANSCRIPT)
    spent = budget.spent("p1")

    artifact = voice.synthesize(SOURCE, replace(wide, fit="stretch"), TRANSCRIPT)

    assert len(post.calls) == 1              # the answer did not call the vendor
    assert budget.spent("p1") == spent       # nor pay again
    assert artifact.duration == pytest.approx(3.87, abs=0.02)
    # A later take is a fresh one.
    voice.synthesize(SOURCE, replace(wide, fit="stretch"), TRANSCRIPT)
    assert len(post.calls) == 2
