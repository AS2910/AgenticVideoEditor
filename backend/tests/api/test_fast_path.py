"""Run 5 item 6, end to end with mocked vendors: a small edit to one line,
sent with Enter, is voiced straight away as one take (no Claude call) and
stands as a proposal ready to hear; anything bigger, or a take that does not
fit, is Voltage's full turn; the spending limit still holds."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, await_job, take, upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)

LINE = {"start": 0.0, "end": 2.3}


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def four_cents(client, sample_video, monkeypatch):
    """A fresh video under Check with me, one line ("Get 20% off today only.", 0 to 2.3 s), a take at $0.04."""
    import app.api.main as main
    assert upload(client, sample_video).status_code == 200
    monkeypatch.setattr(main.voice, "cost_of", lambda plan: 20)
    monkeypatch.setattr(main.budget, "usd_per_1k", 2.0)
    return main


def quick(client, text, **more):
    resp = client.post("/videos/p1/lines/quick", json={**LINE, "text": text, "before": "Get 20% off today only.",
                                                      "turn_text": f"Replace the line at 0:00 with “{text}”", **more})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job = await_job(client, body["job_id"])
    assert job["status"] == "succeeded", job
    return body, job["result"]


def test_a_small_edit_is_voiced_straight_away_as_a_proposal_with_no_claude_call(client, four_cents, monkeypatch):
    scripted = _agent_on(monkeypatch, four_cents, [])          # any call to Claude would find no answer and fail
    body, result = quick(client, "Get 30% off this weekend only.")
    assert body["route"] == "fast" and body["reason"] == "3 words changed"
    assert result["quick"] and result["question"] is None and result["fallback"] is None
    [item] = result["plan"]["items"]
    assert item["status"] == "ready" and item["candidate"]["audio"] and item["new_text"] == "Get 30% off this weekend only."
    assert item["old_text"] == "Get 20% off today only."                    # the line itself, replaced
    assert scripted.calls == []
    assert result["took_s"] >= 0
    said = [m["text"] for m in client.get("/videos/p1/messages").json()]
    assert said[0] == "Replace the line at 0:00 with “Get 30% off this weekend only.”"
    assert any("straight away" in t for t in said)
    # The turn view reads done, with what it spent (the mock voice charges nothing), so the status strip settles.
    view = repo.settings("p1")["turn_view"]
    assert view["status"] == "done" and view["lines_voiced"] == 1 and view["spent_usd"] == 0


def test_the_fast_take_respects_the_spending_limit_under_it_no_approval_over_it_the_full_turn_asks(client, four_cents, monkeypatch):
    # $0.04 under the default $0.25: no card, already proven above. A limit of nothing: the full turn, which asks.
    client.put("/me/settings", json={"ask_over_usd": 0.0})
    from tests.agent.conftest import reply
    _agent_on(monkeypatch, four_cents, [reply(take(text="Get 30% off today only."), stop="tool_use")])
    body, result = quick(client, "Get 30% off today only.")
    assert body["route"] == "full" and body["reason"] == "over your spending limit"
    q = result["question"]
    assert q["gate"] and q["options"][0] == "Voice it · $0.04"


def test_a_big_rewrite_goes_to_the_full_turn_with_the_editor_s_sentence(client, four_cents, monkeypatch):
    from tests.agent.conftest import reply, text
    scripted = _agent_on(monkeypatch, four_cents, [reply(text("Which part should change?"))])
    body, _ = quick(client, "Come in this weekend and every single loaf of bread is half price for members.")
    assert body["route"] == "full" and body["reason"].endswith("words changed")
    assert "Replace the line at 0:00 with" in str(scripted.calls[0]["messages"])


def test_a_new_voice_goes_to_the_full_turn(client, four_cents, monkeypatch):
    from tests.agent.conftest import reply, text
    _agent_on(monkeypatch, four_cents, [reply(text("Done."))])
    body, _ = quick(client, "Get 30% off today only.", voice_id="someone-else")
    assert body["route"] == "full" and body["reason"] == "a different voice"


def test_a_take_that_does_not_fit_hands_over_to_the_full_turn_with_a_note(client, four_cents, monkeypatch):
    _agent_on(monkeypatch, four_cents, [])
    # Eight words changed, far too many syllables for 2.3 s: refused before anything is paid.
    body, result = quick(client, "Get twenty-five percent off absolutely everything, Saturday through Wednesday only.")
    assert body["route"] == "fast"
    assert result["fallback"]["note"].startswith("The new words run long for the gap (") and result["fallback"]["note"].endswith("Voltage is taking it from here.")
    assert result["fallback"]["text"].startswith("Replace the line at 0:00 with")
    assert result["spent_usd"] == 0
    said = [m["text"] for m in client.get("/videos/p1/messages").json()]
    assert result["fallback"]["note"] in said
    # The editor then says the same sentence, with the note, to Voltage as a full turn.
    from tests.agent.conftest import reply, text
    scripted = _agent_on(monkeypatch, four_cents, [reply(text("That runs long for 2.3 s. Try a shorter version?"))])
    resp = client.post("/videos/p1/turns", json={"text": result["fallback"]["text"]})
    assert resp.status_code == 202 and await_job(client, resp.json()["job_id"])["status"] == "succeeded"
    assert "ran long" in str(scripted.calls[0]["messages"]) or "taking it from here" in str(scripted.calls[0]["messages"])


def test_story_checks_run_after_the_take_and_only_suggest(client, four_cents, monkeypatch):
    import app.api.main as main
    from dataclasses import replace
    from app.domain.models import Statement, Transcript, Word
    words = (Word("Get", 0.0, 0.3), Word("20%", 0.3, 0.8), Word("off", 0.8, 1.0), Word("today", 1.0, 1.5), Word("only.", 1.5, 2.0),
             Word("Remember,", 2.1, 2.2), Word("20%", 2.2, 2.25), Word("off.", 2.25, 2.3))
    two = Transcript(words=words, statements=(Statement("Get 20% off today only.", 0.0, 2.0),
                                              Statement("Remember, 20% off.", 2.1, 2.3)))
    real_get = main.repo.get
    monkeypatch.setattr(main.repo, "get", lambda pid: replace(real_get(pid), transcript=two))
    _agent_on(monkeypatch, four_cents, [])
    resp = client.post("/videos/p1/lines/quick", json={"start": 0.0, "end": 2.0, "text": "Get 30% off today only.",
                                                       "before": "Get 20% off today only."})
    assert resp.json()["route"] == "fast"
    result = await_job(client, resp.json()["job_id"])["result"]
    assert result["story"] == ["The line at 0:02 still says 20%, and this one now says 30%."]
    [item] = result["plan"]["items"]
    assert item["status"] == "ready"                                  # a suggestion, never a block
    said = [m["text"] for m in client.get("/videos/p1/messages").json()]
    assert said[-1].startswith("Worth a look: ") and said[-1].endswith("If you meant it, leave it.")


def test_editing_the_proposal_again_in_the_voice_it_opened_on_stays_fast_and_reuses_its_item(client, four_cents, monkeypatch):
    _agent_on(monkeypatch, four_cents, [])
    _, first = quick(client, "Get 30% off today only.")
    [item] = first["plan"]["items"]
    opened_voice = item["candidate"]["plan"]["voice_profile_id"]
    body, second = quick(client, "Get 40% off today only.", before="Get 30% off today only.", voice_id=opened_voice)
    assert body["route"] == "fast"
    [again] = second["plan"]["items"]                       # one line, one item
    assert again["item_id"] == item["item_id"] and again["new_text"] == "Get 40% off today only."
    assert again["candidate"]["candidate_id"] != item["candidate"]["candidate_id"]
