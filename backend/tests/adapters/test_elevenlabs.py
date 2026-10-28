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
    SAMPLE_RATE, _post, to_voice,
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


@needs_ffmpeg
def test_a_take_that_ran_long_is_measured_and_held_for_the_free_rungs_of_the_fit_ladder(store):
    """p61: the take's own spoken length is measured for the voice's rate, and
    the paid take is held, so an earlier start or an eased picture reuses it."""
    from dataclasses import replace
    post = FakePost()
    voice = adapter(store, post=post)
    tiny = EditPlan(Selection(0.4, 0.5), "30% off", "speaker-1")
    assert not voice.holds(SOURCE, tiny, TRANSCRIPT)
    with pytest.raises(ffmpeg.SpanMismatch):
        voice.synthesize(SOURCE, tiny, TRANSCRIPT)
    assert voice.holds(SOURCE, tiny, TRANSCRIPT)
    assert voice.last_measure["speed"] == 1.0 and voice.last_measure["seconds"] > 0.3
    with pytest.raises(ffmpeg.SpanMismatch):
        voice.synthesize(SOURCE, replace(tiny, flex_max=1.25), TRANSCRIPT)
    assert len(post.calls) == 1 and voice.last_measure is None      # reused, so not paid or measured twice


# --- Phase 10: choosing a voice ------------------------------------------------

@needs_ffmpeg
def test_an_edit_can_choose_its_voice(store):
    post = FakePost()
    chosen = EditPlan(Selection(0.4, 1.3), "30% off", "nPczCjzI2devNBz1zQrb")
    adapter(store, post=post).synthesize(SOURCE, chosen, TRANSCRIPT)
    assert post.calls[0][0] == "nPczCjzI2devNBz1zQrb"


@needs_ffmpeg
def test_a_non_voice_id_means_the_default(store):
    post = FakePost()
    adapter(store, post=post).synthesize(SOURCE, PLAN, TRANSCRIPT)   # "speaker-1"
    assert post.calls[0][0] == "voice-x"


def test_voices_are_listed_once_and_named_plainly():
    calls = []

    def get_voices(api_key, timeout):
        calls.append(api_key)
        return [to_voice({"voice_id": "nPczCjzI2devNBz1zQrb",
                          "name": "Brian - Deep, Resonant and Comforting",
                          "labels": {"gender": "male", "accent": "american", "age": "middle_aged"}})]

    voice = ElevenLabsVoiceAdapter(KEY, None, VoiceBudget(ceiling=10), model="m",
                                   voice_id="voice-x", get_voices=get_voices)
    assert voice.voices() == voice.voices()
    assert calls == [KEY]
    [brian] = voice.voices()
    assert (brian["name"], brian["description"], brian["gender"]) == (
        "Brian", "Deep, Resonant and Comforting", "male")


# --- Phase 14: takes by duration, the model's own speed ------------------------

class Takes(FakePost):
    """Returns a different-length take each call: `seconds` in turn."""

    def __init__(self, seconds):
        super().__init__()
        self.seconds = list(seconds)

    def __call__(self, voice_id, body, api_key, timeout):
        self.calls.append((voice_id, body))
        n = min(len(self.calls), len(self.seconds)) - 1
        samples = int(self.seconds[n] * SAMPLE_RATE)
        import numpy as np
        t = np.arange(samples) / SAMPLE_RATE
        pcm = (0.5 * np.sin(2 * np.pi * 300 * t) * 32767).astype("<i2").tobytes()
        return 200, pcm, ""


@needs_ffmpeg
def test_a_first_take_within_tolerance_is_the_only_one_paid_for(store):
    post = Takes([0.92])
    budget = VoiceBudget(ceiling=1000)
    voice = adapter(store, post=post, budget=budget)
    voice._takes = 3
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)       # a 0.9 s slot
    assert len(post.calls) == 1
    assert budget.spent("p1") == billed_characters("30% off", "eleven_multilingual_v2")


@needs_ffmpeg
def test_a_take_that_misses_gets_more_takes_and_the_nearest_wins(store):
    post = Takes([1.3, 0.75, 0.95])
    budget = VoiceBudget(ceiling=1000)
    voice = adapter(store, post=post, budget=budget)
    voice._takes = 3
    artifact = voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(post.calls) == 3
    assert budget.spent("p1") == 3 * billed_characters("30% off", "eleven_multilingual_v2")
    assert artifact.duration == pytest.approx(0.9, abs=0.02)
    assert "nearest of 3 takes" in voice.last_notes


@needs_ffmpeg
def test_takes_stop_at_the_first_close_enough_for_the_ladder(store):
    # Cost 1c (on with AVE_TAKE_EARLY_STOP=1): against a 0.9 s slot, 1.3 s misses, 0.95 s (5.6% long) is close enough at a 10% accept.
    post = Takes([1.3, 0.95, 0.9])
    budget = VoiceBudget(ceiling=1000)
    voice = adapter(store, post=post, budget=budget)
    voice._takes, voice._accept, voice._early_stop = 3, 0.10, True
    artifact = voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(post.calls) == 2
    assert budget.spent("p1") == 2 * billed_characters("30% off", "eleven_multilingual_v2")
    assert artifact.duration == pytest.approx(0.9, abs=0.02) and "nearest of 2 takes" in voice.last_notes
    # With no band set, the search stops at the first take within the tolerance.
    within = Takes([1.3, 0.92, 0.9])
    voice = adapter(store, post=within)
    voice._takes, voice._early_stop = 3, True
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(within.calls) == 2
    # A first take inside the accept band is the only one paid for.
    one = Takes([0.97])
    voice = adapter(store, post=one)
    voice._takes, voice._accept, voice._early_stop = 3, 0.10, True
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(one.calls) == 1


@needs_ffmpeg
def test_when_every_take_is_too_long_the_model_is_asked_to_speak_faster(store):
    # 1.25 s against 0.9 s is 1.39×: past atempo's 1.25, inside 1.25 × 1.15 (p61: no faster than 1.15).
    post = Takes([1.25, 1.25, 1.25, 1.0])
    voice = adapter(store, post=post)
    voice._takes = 3
    artifact = voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(post.calls) == 4
    assert post.calls[3][1]["voice_settings"] == {"speed": 1.15}
    assert artifact.duration == pytest.approx(0.9, abs=0.02)
    assert any("by the model" in n for n in voice.last_notes)


@needs_ffmpeg
def test_an_explicit_fit_or_an_added_line_takes_one_take(store):
    from dataclasses import replace
    post = Takes([2.0])
    voice = adapter(store, post=post)
    voice._takes = 3
    voice.synthesize(SOURCE, replace(PLAN, fit="stretch"), TRANSCRIPT)
    voice.synthesize(SOURCE, replace(PLAN, mix="concatenate"), TRANSCRIPT)
    assert len(post.calls) == 2
    assert "voice_settings" not in post.calls[0][1]


def test_speed_goes_in_the_request_within_the_apis_limits():
    assert to_request(PLAN, None, "m", speed=1.1)["voice_settings"] == {"speed": 1.1}
    assert to_request(PLAN, None, "m", speed=1.9)["voice_settings"] == {"speed": 1.2}
    assert "voice_settings" not in to_request(PLAN, None, "m")


# --- UX-1: delivery ---------------------------------------------------------------

def test_a_delivery_becomes_voice_settings():
    from dataclasses import replace
    assert to_request(replace(PLAN, delivery="more excited"), None, "m")["voice_settings"] == {"stability": 0.3, "style": 0.65}
    assert to_request(replace(PLAN, delivery="slower"), None, "m")["voice_settings"] == {"speed": 0.9}
    # a speed asked for by the fitter combines with a slow delivery, inside the limits
    assert to_request(replace(PLAN, delivery="slower"), None, "m", speed=1.2)["voice_settings"]["speed"] == pytest.approx(1.08)
    assert "voice_settings" not in to_request(replace(PLAN, delivery="in my own words"), None, "m")


# --- P-3: word times from the vendor's alignment -------------------------------

import base64  # noqa: E402

from app.adapters.elevenlabs import decode_response, words_from_alignment  # noqa: E402


def _alignment(text, step=0.1):
    """Each character `step` seconds long, back to back, spaces included."""
    return {
        "characters": list(text),
        "character_start_times_seconds": [round(i * step, 4) for i in range(len(text))],
        "character_end_times_seconds": [round((i + 1) * step, 4) for i in range(len(text))],
    }


def test_characters_fold_into_words_with_their_times():
    words = words_from_alignment(_alignment("30% off"))
    assert [(w.text, w.start, w.end) for w in words] == [("30%", 0.0, 0.3), ("off", 0.4, 0.7)]
    assert words_from_alignment(None) == () and words_from_alignment({}) == ()


def test_a_with_timestamps_response_yields_audio_and_words():
    body = json.dumps({"audio_base64": base64.b64encode(PCM).decode("ascii"),
                       "alignment": _alignment("30% off")}).encode()
    audio, words = decode_response(body)
    assert audio == PCM and [w.text for w in words] == ["30%", "off"]
    # A bare PCM response (the recording, a stand-in) is the audio, no words.
    assert decode_response(PCM) == (PCM, ())


def test_the_call_goes_to_the_with_timestamps_endpoint(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        return httpx.Response(200, content=PCM)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert _post("voice-x", {"text": "hi"}, KEY, 1.0)[0] == 200
    assert seen["url"].endswith("/text-to-speech/voice-x/with-timestamps")


@needs_ffmpeg
def test_the_takes_words_come_out_fitted_on_the_adapter(store):
    seconds = len(PCM) / 2 / SAMPLE_RATE
    alignment = {
        "characters": list("30% off"),
        "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, round(seconds, 3)],
    }
    body = json.dumps({"audio_base64": base64.b64encode(PCM).decode("ascii"), "alignment": alignment}).encode()
    voice = adapter(store, post=FakePost(content=body))
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert [w.text for w in voice.last_words] == ["30%", "off"]
    assert voice.last_words[1].start >= voice.last_words[0].end
    assert voice.last_words[1].end <= 0.9 + 0.05            # inside the fitted take


# --- 15e: the catalogue holds the library's voices too; clones never -----------

def test_the_catalogue_lists_premade_and_library_voices_but_never_a_clone():
    from app.adapters.elevenlabs import in_catalogue
    raw = [
        {"voice_id": "kL06KYMvPY56NluIQ72m", "name": "Varsha - Warm and Clear", "category": "professional",
         "labels": {"gender": "female", "accent": "indian", "age": "middle_aged"}},
        {"voice_id": "nPczCjzI2devNBz1zQrb", "name": "Brian - Deep, Resonant and Comforting", "category": "premade",
         "labels": {"gender": "male", "accent": "american", "age": "middle_aged"}},
        {"voice_id": "c" * 20, "name": "voltage-p3-A", "category": "cloned", "labels": {}},
        {"voice_id": "d" * 20, "name": "My own clone", "category": "cloned", "labels": {}},
    ]
    kept = [to_voice(v) for v in raw if in_catalogue(v)]
    assert [v["name"] for v in kept] == ["Varsha", "Brian"]
    assert kept[0]["category"] == "professional" and kept[0]["accent"] == "indian"


def test_adding_a_library_voice_refreshes_the_catalogue_and_a_refusal_is_a_plain_error():
    import pytest
    from app.adapters.elevenlabs import VoiceConfigError
    listed = []
    added = []

    def get_voices(api_key, timeout):
        listed.append(1)
        return [{"voice_id": "v" * 20, "name": "Varsha"}] if added else []

    def add_from_library(api_key, owner_id, voice_id, name, timeout):
        added.append((owner_id, voice_id, name))
        return (200, voice_id, "") if name != "refused" else (402, "", "voice slots are full")

    voice = ElevenLabsVoiceAdapter(KEY, None, VoiceBudget(ceiling=10), model="m", voice_id="voice-x",
                                   get_voices=get_voices, add_from_library=add_from_library)
    assert voice.voices() == []
    assert voice.add_from_library("owner1", "v" * 20, "Varsha") == "v" * 20
    assert [v["name"] for v in voice.voices()] == ["Varsha"]
    assert added == [("owner1", "v" * 20, "Varsha")] and len(listed) == 2
    with pytest.raises(VoiceConfigError, match="voice slots are full"):
        voice.add_from_library("owner1", "w" * 20, "refused")


# --- 20b: tags, models, settings; a voice from words -----------------------------

def test_tags_stay_for_v3_and_v4_and_go_for_v2_and_the_context_follows_the_model():
    from dataclasses import replace
    from app.adapters.elevenlabs import spoken_text, has_tags, clamp_settings
    tagged = replace(PLAN, new_text="[sighs] 30% off")
    assert to_request(replace(tagged, model="v4"), TRANSCRIPT, "eleven_multilingual_v2") == {
        "text": "[sighs] 30% off", "model_id": "eleven_v4", "previous_text": "Get", "next_text": "today only"}
    v3 = to_request(replace(tagged, model="eleven_v3"), TRANSCRIPT, "eleven_multilingual_v2")
    assert v3 == {"text": "[sighs] 30% off", "model_id": "eleven_v3"}          # no context for v3
    assert to_request(tagged, TRANSCRIPT, "eleven_multilingual_v2")["text"] == "30% off"   # v2 would read the tag
    assert spoken_text("A [long pause] word  [x]", "eleven_flash_v2_5") == "A word" and has_tags("[sighs] hi") and not has_tags("hi [")
    assert clamp_settings({"stability": 1.4, "style": -1, "speed": 0.2, "similarity_boost": 0.5, "use_speaker_boost": 1, "junk": 3, "speed2": None}) == {
        "stability": 1.0, "style": 0.0, "speed": 0.7, "similarity_boost": 0.5, "use_speaker_boost": True}


def test_explicit_settings_win_over_the_delivery_and_the_fitters_speed_folds_in():
    from dataclasses import replace
    plan = replace(PLAN, delivery="more excited", voice_settings={"stability": 0.4, "speed": 0.9})
    assert to_request(plan, None, "m")["voice_settings"] == {"stability": 0.4, "speed": 0.9}
    assert to_request(plan, None, "m", speed=1.1)["voice_settings"]["speed"] == pytest.approx(0.99)


def test_the_cost_counts_the_text_as_sent(store):
    from dataclasses import replace
    v = adapter(store)
    assert v.cost_of(replace(PLAN, new_text="[sighs] 30% off", model="v3")) == 15
    assert v.cost_of(replace(PLAN, new_text="[sighs] 30% off")) == 7
    assert v.model == "eleven_multilingual_v2"


def test_a_tags_span_stays_in_the_audio_and_leaves_the_words():
    words = words_from_alignment(_alignment("[sighs] 30% [long pause] off"))
    assert [w.text for w in words] == ["30%", "off"]
    assert words[0].start == pytest.approx(0.8)


def test_a_voice_is_designed_charged_by_its_sample_text_and_a_preview_kept_as_a_voice():
    from app.adapters.elevenlabs import DESIGN_CHARS
    calls = []
    sample = "x" * 420

    def design(api_key, description, text, timeout):
        calls.append(("design", description, text))
        return 200, {"text": sample, "previews": [
            {"generated_voice_id": "g1", "audio_base_64": base64.b64encode(b"one").decode(), "media_type": "audio/mpeg", "duration_secs": 25.2},
            {"generated_voice_id": "g2", "audio_base_64": base64.b64encode(b"two").decode(), "media_type": "audio/mpeg", "duration_secs": 26.0},
        ]}, ""

    def create_voice(api_key, name, description, gid, timeout):
        calls.append(("create", name, description, gid))
        return 200, "NEWV" + gid, ""

    budget = VoiceBudget(ceiling=2000)
    v = ElevenLabsVoiceAdapter(KEY, None, budget, model="m", voice_id="voice-x", design=design, create_voice=create_voice,
                               get_voices=lambda k, t: [], subscription=lambda k, t: {"voice_slots_used": 4, "voice_limit": 30})
    previews = v.design_voice("p1", "an older woman", None)
    assert [p["generated_voice_id"] for p in previews] == ["g1", "g2"] and previews[0]["audio"] == b"one"
    assert previews[1]["duration"] == 26.0 and previews[0]["text"] == sample
    # charged DESIGN_CHARS up front, trued up to the 420-character sample the vendor used
    assert budget.remaining("p1") == 2000 - 420 and DESIGN_CHARS == 350
    assert v.save_voice("g2", "Dusk", "an older woman") == "NEWVg2"
    assert calls == [("design", "an older woman", None), ("create", "Dusk", "an older woman", "g2")]
    assert v.slots() == (4, 30) and v.design_cost() == 350
    with pytest.raises(VoiceConfigError, match="at least 100 characters"):
        v.design_voice("p1", "a man", "short")


def test_a_failed_design_refunds_and_a_refusal_is_a_plain_error():
    budget = VoiceBudget(ceiling=1000)
    v = ElevenLabsVoiceAdapter(KEY, None, budget, model="m", voice_id="voice-x",
                               design=lambda k, d, t, to: (402, {}, "quota exceeded"), subscription=lambda k, t: {})
    with pytest.raises(VoiceConfigError, match="quota"):
        v.design_voice("p1", "a man", None)
    assert budget.remaining("p1") == 1000 and v.slots() is None
