"""A question the turn's cap caused (pane-render, 2026-10-20): its first option
raises this turn's cap by exactly what the refused step needs and carries the
same turn on; the raise is refused, naming the scope, past a ceiling. And the
ask tool's options carry an optional detail line end to end."""
import math

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, await_job, send, take, upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)

ASK = {"question": "The new line is over this turn's cap. What should I do?",
       "options": [{"label": "Voice it next turn", "detail": "Voice the shorter middle line next turn, then add all five."},
                   {"label": "Let me listen first", "detail": ""}],
       "guess": "Voice it next turn"}


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def capped(client, sample_video, monkeypatch):
    """A video under Just do it whose turn cap ($0.01) is below one take."""
    import app.api.main as main
    assert upload(client, sample_video).status_code == 200
    monkeypatch.setattr(main.voice, "cost_of", lambda plan: 20)           # 20 characters a take
    monkeypatch.setattr(main.budget, "usd_per_1k", 2.0)
    client.put("/videos/p1/settings", json={"autonomy": "draft", "turn_usd": 0.01})
    return main


def over_the_cap(client, main, monkeypatch):
    """A turn whose take the cap refuses; Voltage then asks."""
    from tests.agent.conftest import reply, use
    _agent_on(monkeypatch, main, [reply(take(), stop="tool_use"), reply(use("ask", "a1", **ASK), stop="tool_use")])
    return send(client, "make it 30% off")


def test_a_cap_question_offers_exactly_what_the_step_needs_first(client, capped, monkeypatch):
    main = capped
    _, step = main._workbench().estimate_usd("Get 30% off today only.")
    result = over_the_cap(client, main, monkeypatch)
    q = result["question"]
    spent = main.ledger.spent_usd("p1")                      # this turn's thinking, all of it so far
    needed = math.ceil(round((spent + step - 0.01) * 100, 6)) / 100
    assert q["turn_cap"]["needed_usd"] == needed and q["turn_cap"]["cap_usd"] == 0.01
    assert q["options"] == [f"Go ahead, allow ${needed:.2f} more", "Voice it next turn", "Let me listen first"]
    assert q["details"] == [f"Raises this turn's cap to ${0.01 + needed:.2f} and carries on.",
                            "Voice the shorter middle line next turn, then add all five.", None]
    assert q["guess"] == "Voice it next turn" and q["cap_usd"] == 0.01 and q["left_usd"] == round(max(0.0, 0.01 - spent), 2)
    assert result["plan"]["question"]["turn_cap"]["needed_usd"] == needed


def test_allow_more_raises_this_turns_cap_and_carries_the_turn_on(client, capped, monkeypatch):
    from tests.agent.conftest import reply, text as said
    main = capped
    first = over_the_cap(client, main, monkeypatch)
    needed = first["question"]["turn_cap"]["needed_usd"]
    turn_id = main.repo.settings("p1")["last_turn"]["id"]

    scripted = _agent_on(monkeypatch, main, [reply(take(), stop="tool_use"), reply(said("Hear it."))])
    resp = client.post("/videos/p1/turns/allow-more")
    assert resp.status_code == 202, resp.text
    job = await_job(client, resp.json()["job_id"])
    assert job["status"] == "succeeded", job
    [item] = job["result"]["plan"]["items"]
    assert item["status"] == "ready"                        # the refused take ran this time
    told = str(scripted.calls[0]["messages"][-1]["content"])
    assert f"They allowed ${needed:.2f} more for this turn" in told
    # The same turn: its id, and its cap raised by exactly what was needed.
    last = main.repo.settings("p1")["last_turn"]
    assert last["id"] == turn_id and last["cap_usd"] == round(0.01 + needed, 2)
    assert job["result"]["spend"]["turn"]["ceiling_usd"] == round(0.01 + needed, 2)
    assert job["result"]["spend"]["turn"]["spent_usd"] == pytest.approx(main.ledger.spent_usd("p1"), abs=1e-4)


def test_allow_more_is_refused_past_the_video_ceiling_and_says_so(client, capped, monkeypatch):
    main = capped
    first = over_the_cap(client, main, monkeypatch)
    spent = main.ledger.spent_usd("p1")
    main.ledger.record("p1", "elevenlabs", "speech", 1, "characters", 2.0 - spent - first["question"]["turn_cap"]["needed_usd"] / 2)
    resp = client.post("/videos/p1/turns/allow-more")
    assert resp.status_code == 409
    assert "past its $2 video ceiling" in resp.json()["detail"]
    assert client.get("/jobs/j2").status_code == 404        # nothing was queued


def test_allow_more_is_refused_past_the_project_ceiling_and_names_it(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.api.test_folders import upload_into
    fid = client.post("/projects", json={"name": "Boxing"}).json()["project_id"]
    client.patch(f"/projects/{fid}", json={"ceiling_usd": 1.0})
    assert upload_into(client, sample_video, fid).status_code == 200
    monkeypatch.setattr(main.voice, "cost_of", lambda plan: 20)           # 20 characters a take
    monkeypatch.setattr(main.budget, "usd_per_1k", 2.0)
    client.put("/videos/p1/settings", json={"autonomy": "draft", "turn_usd": 0.01})
    over_the_cap(client, main, monkeypatch)
    main.ledger.record_project_level(fid, "elevenlabs", "voice design", 1, "characters", 0.999)
    resp = client.post("/videos/p1/turns/allow-more")
    assert resp.status_code == 409
    assert "Boxing past its $1 project ceiling" in resp.json()["detail"]


def test_allow_more_needs_a_cap_question(client, capped):
    assert client.post("/videos/p1/turns/allow-more").status_code == 409


def test_an_answer_with_a_detail_reaches_voltage_in_full(client, capped, monkeypatch):
    from tests.agent.conftest import reply, use, text as said
    main = capped
    client.put("/videos/p1/settings", json={"turn_usd": 0.5})
    _agent_on(monkeypatch, main, [reply(use("ask", "a1", **ASK), stop="tool_use")])
    q = send(client, "make it 30% off")["question"]
    assert "turn_cap" not in q and q["options"] == ["Voice it next turn", "Let me listen first"]
    assert q["details"] == ["Voice the shorter middle line next turn, then add all five.", None]
    scripted = _agent_on(monkeypatch, main, [reply(said("Fine."))])
    send(client, "Voice it next turn")
    told = str(scripted.calls[0]["messages"][-1]["content"])
    assert "They picked “Voice it next turn”: Voice the shorter middle line next turn, then add all five." in told
