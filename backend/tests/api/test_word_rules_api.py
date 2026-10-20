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
    assert client.get(f"/projects/f1/rules/{word['rule_id']}/audio").headers["content-type"] == "audio/wav"
    long, _ = ffmpeg.generate_tone(tmp_path / "long.wav", 12.0, 440)
    with open(long, "rb") as handle:
        assert client.post(f"/projects/f1/rules/{word['rule_id']}/audio", files={"file": ("long.wav", handle, "audio/wav")}).status_code == 422
    assert "audio" not in client.delete(f"/projects/f1/rules/{word['rule_id']}/audio").json()["data"]
    assert client.get(f"/projects/f1/rules/{word['rule_id']}/audio").status_code == 404
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
