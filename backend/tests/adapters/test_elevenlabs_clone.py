"""Cloning through the ElevenLabs adapter (Phase 15a). No network, no spend."""
import math

import pytest

from app.adapters.elevenlabs import ElevenLabsVoiceAdapter, VoiceConfigError, VoiceError, _raise_for
from app.budget import VoiceBudget
from app.domain.models import EditPlan, Selection

KEY = "sk_test_never_real_0123456789"
CLONE = "C" * 20
STOCK = "S" * 20


class FakeAdd:
    def __init__(self, status=200, voice_id=CLONE, text=""):
        self.status, self.voice_id, self.text = status, voice_id, text
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, api_key, name, wav, timeout):
        self.calls.append((name, wav))
        return self.status, self.voice_id if self.status == 200 else "", self.text


class FakeDelete:
    def __init__(self, status=200, text=""):
        self.status, self.text = status, text
        self.calls: list[str] = []

    def __call__(self, api_key, voice_id, timeout):
        self.calls.append(voice_id)
        return self.status, self.text


def adapter(store, add=None, delete=None):
    return ElevenLabsVoiceAdapter(
        KEY, store, VoiceBudget(ceiling=1000), model="eleven_multilingual_v2", voice_id=STOCK,
        add_voice=add or FakeAdd(), delete_voice=delete or FakeDelete(),
    )


@pytest.fixture()
def reference(tmp_path):
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfake")
    return path


def plan(voice):
    return EditPlan(Selection(0.4, 1.3), "30% off", voice)


def test_a_clone_is_made_from_the_reference_and_remembered(store, reference):
    add = FakeAdd()
    a = adapter(store, add=add)
    assert a.create_clone("voltage-p1-A", reference) == CLONE
    assert add.calls == [("voltage-p1-A", b"RIFF....WAVEfake")]
    assert a.identity_for(plan(CLONE)) == "clone"


def test_only_a_voice_known_to_be_a_clone_is_labelled_clone(store, reference):
    a = adapter(store)
    assert a.identity_for(plan(STOCK)) == "stock"
    assert a.identity_for(plan("speaker-1")) == "stock"          # the UI's legacy id: the default voice
    a.register_clone(CLONE)                                       # a clone made in an earlier run
    assert a.identity_for(plan(CLONE)) == "clone"


def test_deleting_a_clone_forgets_it_and_treats_already_gone_as_done(store):
    delete = FakeDelete(status=404)
    a = adapter(store, delete=delete)
    a.register_clone(CLONE)
    a.delete_clone(CLONE)
    assert delete.calls == [CLONE]
    assert a.identity_for(plan(CLONE)) == "stock"


def test_a_failed_delete_is_an_error_not_a_silent_leftover(store):
    a = adapter(store, delete=FakeDelete(status=500))
    with pytest.raises(VoiceError):
        a.delete_clone(CLONE)


@pytest.mark.parametrize("status, text, expect", [
    (401, '{"detail":{"status":"missing_permissions","message":"The API key you used is missing the permission voices_write to execute this operation."}}', "voices_write"),
    (400, '{"detail":{"status":"voice_limit_reached","message":"..."}}', "no voice slot"),
    (401, "unauthorized", "rejected the API key"),
])
def test_a_refused_clone_says_why_in_a_sentence(store, reference, status, text, expect):
    a = adapter(store, add=FakeAdd(status=status, text=text))
    with pytest.raises(VoiceConfigError, match=expect):
        a.create_clone("n", reference)
    assert a.identity_for(plan(CLONE)) == "stock"


def test_a_vendor_outage_while_cloning_is_retryable(store, reference):
    a = adapter(store, add=FakeAdd(status=503))
    with pytest.raises(VoiceError):
        a.create_clone("n", reference)


def test_the_key_never_appears_in_a_refusal(store, reference):
    a = adapter(store, add=FakeAdd(status=400, text=f"bad request for {KEY}"))
    with pytest.raises(VoiceConfigError) as err:
        a.create_clone("n", reference)
    assert KEY not in str(err.value)


def test_raise_for_names_a_missing_permission():
    with pytest.raises(VoiceConfigError, match="models_read"):
        _raise_for(401, "The API key you used is missing the permission models_read to execute this operation.")


# --- the Voice Changer (Phase 15b) -------------------------------------------

from pathlib import Path as _Path  # noqa: E402

from app.budget import BudgetExceeded  # noqa: E402
from app.domain.models import MediaArtifact  # noqa: E402
from app.media import ffmpeg  # noqa: E402
from tests.factories import make_source  # noqa: E402

PCM = (_Path(__file__).parents[1] / "fixtures" / "elevenlabs-tts.pcm").read_bytes()
needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


class FakeConvert:
    def __init__(self, status=200, content=PCM, text=""):
        self.status, self.content, self.text = status, content, text
        self.calls: list[tuple[str, int]] = []

    def __call__(self, api_key, voice_id, wav, timeout):
        self.calls.append((voice_id, len(wav)))
        return self.status, self.content if self.status == 200 else b"", self.text


def changer(store, convert, ceiling=1000):
    budget = VoiceBudget(ceiling=ceiling)
    a = ElevenLabsVoiceAdapter(
        KEY, store, budget, model="eleven_multilingual_v2", voice_id=STOCK,
        add_voice=FakeAdd(), delete_voice=FakeDelete(), convert=convert,
    )
    a.register_clone(CLONE)
    return a, budget


@pytest.fixture()
def take(store, tmp_path):
    wav, duration = ffmpeg.generate_tone(tmp_path / "take.wav", 0.9, 220)
    return store.put_file("p1", wav, kind="audio", container="wav", duration=duration)


@needs_ffmpeg
def test_a_take_is_passed_through_the_clone_and_keeps_its_length(store, take):
    convert = FakeConvert()
    a, budget = changer(store, convert)
    out = a.revoice(make_source(project_id="p1"), plan(CLONE), take)
    assert convert.calls[0][0] == CLONE
    assert out.kind == "audio" and out.duration == pytest.approx(take.duration, abs=0.03)
    assert out.sha256 != take.sha256


@needs_ffmpeg
def test_only_a_take_in_a_clone_can_be_converted(store, take):
    convert = FakeConvert()
    a, _ = changer(store, convert)
    assert a.revoice(make_source(project_id="p1"), plan(STOCK), take) is None
    assert convert.calls == []


@needs_ffmpeg
def test_the_conversion_is_billed_by_the_second_and_refunded_when_it_fails(store, take):
    a, budget = changer(store, FakeConvert(status=503))
    before = budget.remaining("p1")
    with pytest.raises(VoiceError):
        a.revoice(make_source(project_id="p1"), plan(CLONE), take)
    assert budget.remaining("p1") == before                       # nothing came back, nothing charged

    ok, budget = changer(store, FakeConvert())
    ok.revoice(make_source(project_id="p1"), plan(CLONE), take)
    assert budget.remaining("p1") == 1000 - 16                    # ceil(0.9 s * 17)


@needs_ffmpeg
def test_the_conversion_cannot_overspend_the_budget(store, take):
    convert = FakeConvert()
    a, _ = changer(store, convert, ceiling=5)
    with pytest.raises(BudgetExceeded):
        a.revoice(make_source(project_id="p1"), plan(CLONE), take)
    assert convert.calls == []


# --- Run 5 item 7: the original line as the delivery reference ----------------

def _spoken_source(tmp_path):
    from app.domain.models import MediaArtifact
    from tests.factories import make_source as _make
    wav, duration = ffmpeg.generate_tone(tmp_path / "src.wav", 2.0, 180)
    return _make(project_id="p1", media=MediaArtifact("audio", "s" * 64, str(wav), duration, "wav"), duration=duration)


@needs_ffmpeg
def test_a_line_whose_words_stay_is_the_original_converted_into_the_voice(store, tmp_path):
    from app.domain.models import Transcript, Word
    convert = FakeConvert()
    a, budget = changer(store, convert)
    source = _spoken_source(tmp_path)
    words = Transcript(words=(Word("twenty", 0.4, 0.8), Word("off", 0.85, 1.3)))
    out = a.speak_like(source, plan(STOCK), words)
    assert convert.calls[0][0] == STOCK                       # any voice, not only a clone
    assert convert.calls[0][1] > 0                            # the original span was sent
    sel = plan(STOCK).selection
    assert out.duration == pytest.approx(sel.end - sel.start, abs=0.03)
    assert budget.remaining("p1") == 1000 - math.ceil((sel.end - sel.start) * 17)
    assert all(w.start >= -0.03 for w in a.last_words)


@needs_ffmpeg
def test_carrying_the_delivery_is_refunded_when_the_vendor_fails(store, tmp_path):
    a, budget = changer(store, FakeConvert(status=503))
    with pytest.raises(VoiceError):
        a.speak_like(_spoken_source(tmp_path), plan(STOCK), None)
    assert budget.remaining("p1") == 1000
