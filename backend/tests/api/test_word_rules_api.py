"""A3 through the API: a project word gets an example clip; a take is held
against the project's words before it is kept (one that says a glossary term
otherwise is marked and never Voltage's to add); the vendor is sent the
respelling while the line keeps its words; a banned word the user typed
warns and is voiced."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, flags, jobs, repo
from app.domain.models import Word
from app.media import ffmpeg
from tests.api.test_endpoints import send, take, _agent_on
from tests.api.test_folders import upload_into
from tests.factories import media_get

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.consistency", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def project_with_words(client, sample_video):
    client.post("/projects", json={"name": "Diwali", "brief": "Bright."})
    word = client.post("/projects/f1/rules", json={"kind": "pronounce", "data": {"term": "Bhaji Cam", "say": "BAH-jee cam", "respell": "Bah jee cam"}}).json()
    client.post("/projects/f1/rules", json={"kind": "banned", "data": {"word": "cheap"}})
    upload_into(client, sample_video, "f1")
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    return word


def heard(monkeypatch, *words):
    """What the voice vendor's alignment says the take said."""
    import app.api.main as main
    monkeypatch.setattr(main.voice, "last_words", tuple(Word(w, 0.3 * k, 0.3 * k + 0.25) for k, w in enumerate(words)), raising=False)


def test_a_word_takes_an_example_clip_kept_with_the_project(client, sample_video, tmp_path):
    word = project_with_words(client, sample_video)
    clip, _ = ffmpeg.generate_tone(tmp_path / "say.wav", 1.5, 440)
    with open(clip, "rb") as handle:
        got = client.post(f"/projects/f1/rules/{word['rule_id']}/audio", files={"file": ("say.wav", handle, "audio/wav")})
    assert got.status_code == 200, got.text
    assert len(got.json()["data"]["audio"]) == 64 and got.json()["data"]["respell"] == "Bah jee cam"
    assert media_get(client, f"/projects/f1/rules/{word['rule_id']}/audio").headers["content-type"] == "audio/wav"
    long, _ = ffmpeg.generate_tone(tmp_path / "long.wav", 12.0, 440)
    with open(long, "rb") as handle:
        assert client.post(f"/projects/f1/rules/{word['rule_id']}/audio", files={"file": ("long.wav", handle, "audio/wav")}).status_code == 422
    assert "audio" not in client.delete(f"/projects/f1/rules/{word['rule_id']}/audio").json()["data"]
    assert media_get(client, f"/projects/f1/rules/{word['rule_id']}/audio").status_code == 404
    flags.set("projects.consistency", "local", False)
    with open(clip, "rb") as handle:
        assert client.post(f"/projects/f1/rules/{word['rule_id']}/audio", files={"file": ("say.wav", handle, "audio/wav")}).status_code == 404


def test_a_take_that_mispronounces_a_glossary_term_is_marked_and_voltage_does_not_add_it(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    project_with_words(client, sample_video)
    heard(monkeypatch, "Try", "Badge", "Cam", "today.")
    scripted = _agent_on(monkeypatch, main, [reply(take(text="Try Bhaji Cam today."), stop="tool_use"),
                                             reply(use("ship", "tu2", item_ids=[], anyway=False), stop="tool_use"),
                                             reply(text("Voiced it; the brand name came out wrong, so it is not added."))])
    send(client, "make the line about Bhaji Cam")
    item = repo.latest_plan("p1").items[0]
    assert item.status == "ready" and item.word_rule["breaks"]
    assert item.word_rule["breaks"][0].startswith("“Bhaji Cam” did not come out as written")
    assert main.voice.last_sent_text == "Try Bah jee cam today."          # the vendor got the respelling
    assert item.new_text == "Try Bhaji Cam today."                       # the line keeps its words
    assert repo.list_edits("p1") == []                                    # Voltage's ship skipped it
    told = str(scripted.calls[1]["messages"])
    assert "Breaks a word rule" in told and "breaks a word rule" in str(scripted.calls[2]["messages"])
    shown = client.get("/videos/p1").json()["plan"]["items"][0]
    assert shown["word_rule"]["breaks"]
    # The user may still add it by hand.
    assert client.post("/videos/p1/edits", json={"candidate_id": item.candidate_id}).status_code == 200


def test_a_take_that_says_the_term_right_passes_and_ships(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    project_with_words(client, sample_video)
    heard(monkeypatch, "Try", "Bah", "jee", "cam", "today.")
    _agent_on(monkeypatch, main, [reply(take(text="Try Bhaji Cam today."), stop="tool_use"),
                                  reply(use("ship", "tu2", item_ids=[], anyway=False), stop="tool_use"), reply(text("Done."))])
    send(client, "make the line about Bhaji Cam")
    assert repo.latest_plan("p1").items[0].word_rule is None
    assert len(repo.list_edits("p1")) == 1


def test_a_banned_word_in_a_user_typed_line_warns_but_does_not_block(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    project_with_words(client, sample_video)
    heard(monkeypatch, "Cheap", "deals", "today.")
    _agent_on(monkeypatch, main, [reply(take(text="Cheap deals today."), stop="tool_use"),
                                  reply(use("ship", "tu2", item_ids=[], anyway=False), stop="tool_use"), reply(text("Added."))])
    send(client, "Replace the line at 0:00 with “Cheap deals today.”")
    item = repo.latest_plan("p1").items[0]
    assert item.word_rule == {"breaks": [], "warnings": ["Uses “cheap”, a banned word in this project. Kept, because you typed it."]}
    assert len(repo.list_edits("p1")) == 1                                # voiced and added: a warning, never a block


# ── 9a: the take is heard (Whisper on the take), not read from the vendor's alignment ──

class _Ears:
    """The mock transcriber, made to hear chosen words in a take."""

    def __init__(self, *words):
        from app.adapters.mock import MockTranscriptionAdapter
        self.inner, self.words, self.calls = MockTranscriptionAdapter(), list(words), 0

    def hear(self, source):
        self.calls += 1
        assert source.media.kind == "audio" and source.duration > 0
        return list(self.words)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _whisper_hears(monkeypatch, *words):
    import app.api.main as main
    ears = _Ears(*words)
    monkeypatch.setattr(main, "transcriber", ears)
    monkeypatch.setattr(main, "transcriber_label", "openai:whisper-1")
    return ears


def _voice_one_take(monkeypatch, main):
    from tests.agent.conftest import reply, text
    _agent_on(monkeypatch, main, [reply(take(text="Try Bhaji Cam today."), stop="tool_use"), reply(text("Voiced it."))])


def test_a_mispronounced_term_is_caught_by_hearing_the_take_and_the_minutes_are_charged(client, sample_video, monkeypatch):
    import app.api.main as main
    project_with_words(client, sample_video)
    heard(monkeypatch, "Try", "Bhaji", "Cam", "today.")            # the vendor's alignment repeats the text
    ears = _whisper_hears(monkeypatch, "Try", "Badge", "Cam", "today.")
    _voice_one_take(monkeypatch, main)
    send(client, "make the line about Bhaji Cam")
    item = repo.latest_plan("p1").items[0]
    assert ears.calls == 1
    assert item.word_rule and item.word_rule["breaks"][0].startswith("“Bhaji Cam” did not come out as written")
    assert "badge" in item.word_rule["breaks"][0]
    charged = [ln for ln in main.ledger.lines("p1") if ln.what == "take_check"]
    assert len(charged) == 1 and charged[0].vendor == "openai" and charged[0].unit == "minutes" and charged[0].usd > 0


def test_a_take_heard_saying_the_term_right_passes(client, sample_video, monkeypatch):
    import app.api.main as main
    project_with_words(client, sample_video)
    heard(monkeypatch, "Try", "Bhaji", "Cam", "today.")
    _whisper_hears(monkeypatch, "Try", "Bhajicam", "today.")
    _voice_one_take(monkeypatch, main)
    send(client, "make the line about Bhaji Cam")
    assert repo.latest_plan("p1").items[0].word_rule is None


def test_the_take_is_not_heard_with_the_flag_off_or_a_mock_transcriber(client, sample_video, monkeypatch):
    import app.api.main as main
    project_with_words(client, sample_video)
    heard(monkeypatch, "Try", "Bhaji", "Cam", "today.")
    ears = _whisper_hears(monkeypatch, "Try", "Badge", "Cam", "today.")
    flags.set("projects.consistency", "local", False)
    _voice_one_take(monkeypatch, main)
    send(client, "make the line about Bhaji Cam")
    assert ears.calls == 0 and repo.latest_plan("p1").items[0].word_rule is None
    assert not [ln for ln in main.ledger.lines("p1") if ln.what == "take_check"]


def test_hear_take_needs_a_real_transcriber_and_survives_a_failure():
    from types import SimpleNamespace
    from app.adapters.mock import MockTranscriptionAdapter
    from app.agent.take_hearing import hear_take
    charges = []
    ledger = SimpleNamespace(record=lambda *a: charges.append(a))
    audio = SimpleNamespace(kind="audio", path="/x.wav", duration=3.0, sha256="0")
    candidate = SimpleNamespace(candidate_id="c1", audio=audio)
    mock = MockTranscriptionAdapter()
    assert hear_take("p1", candidate, transcriber=mock, label="mock", ledger=ledger, enabled=lambda: True) is None
    assert hear_take("p1", candidate, transcriber=mock, label="dry-run", ledger=ledger, enabled=lambda: True) is None
    got = hear_take("p1", candidate, transcriber=mock, label="openai:whisper-1", ledger=ledger, enabled=lambda: True)
    assert got == [w.text for w in mock.transcribe(None).words] and got[0] == "Get"
    assert charges == [("p1", "openai", "take_check", 0.05, "minutes", 0.05 * 0.006)]

    class Broken:
        def hear(self, source):
            raise RuntimeError("vendor down")
    assert hear_take("p1", candidate, transcriber=Broken(), label="openai:whisper-1", ledger=ledger, enabled=lambda: True) is None
    assert len(charges) == 1
