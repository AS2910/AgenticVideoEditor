"""F4 through the API: a batch turn plans across a project's videos, opens one
gate, then runs one ordinary turn per video three at a time under the
parent's cap. A failing video never stops the rest; cancelling stops the
queued videos while the running ones finish; Usage counts exactly what the
children spent; a batch above the project's ceiling does not start; a video
with a question pauses alone. Claude is scripted per video (no spend)."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, batch_engine, flags, jobs, ledger, repo
from app.media import ffmpeg
from app.usage import current_turn
from tests.api.test_folders import upload_into
from tests.agent.conftest import reply, text, use

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")

ASK = {"question": "Should the offer say 30% or 25%?",
       "options": [{"label": "30%", "detail": ""}, {"label": "25%", "detail": ""}], "guess": "30%"}


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.batch", "local")


@pytest.fixture()
def client():
    return TestClient(app)


class PerVideo:
    """A scripted Claude that answers each video's turn from that video's own
    script (turns run side by side, so one shared queue would not do). A
    script entry that is an Exception is raised: that video's turn fails.
    `gate` (an Event) holds every call until it is set; `running` counts the
    calls inside at once."""

    def __init__(self, scripts: dict, gate: threading.Event | None = None):
        from types import SimpleNamespace
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.gate = gate
        self.lock = threading.Lock()
        self.inside = 0
        self.most = 0
        self.entered: list[str] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        video = jobs.get(current_turn.get()).project_id
        with self.lock:
            self.inside += 1
            self.most = max(self.most, self.inside)
            self.entered.append(video)
            step = self.scripts[video].pop(0) if self.scripts.get(video) else reply(text("Nothing to change here."))
        try:
            if self.gate is not None:
                self.gate.wait(10)
            else:
                time.sleep(0.05)
            if isinstance(step, Exception):
                raise step
            return step
        finally:
            with self.lock:
                self.inside -= 1


def agent(monkeypatch, scripts, gate=None) -> PerVideo:
    from dataclasses import replace
    import app.api.main as main
    from app.agent.loop import Agent
    monkeypatch.setattr(main, "settings", replace(main.settings, agent=True, anthropic_api_key="k"))
    fake = PerVideo(scripts, gate)
    monkeypatch.setattr(main, "_agent_instance", Agent(fake))
    return fake


def five(client, sample_video):
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    for i in range(1, 6):
        assert upload_into(client, sample_video, "f1", name=f"ad{i}.mp4").status_code == 200
    return [f"p{i}" for i in range(1, 6)]


def plan(client, goal="Make the offer line say 30% off", **more):
    resp = client.post("/projects/f1/batches", json={"goal": goal, **more})
    assert resp.status_code == 201, resp.text
    return resp.json()


def finished(client, batch_id, timeout=120.0):
    batch_engine.wait(batch_id, timeout)
    return client.get(f"/projects/f1/batches/{batch_id}").json()


def test_the_gate_has_the_totals_and_nothing_runs_before_go(client, sample_video, monkeypatch):
    videos = five(client, sample_video)
    fake = agent(monkeypatch, {})
    gate = plan(client)
    assert gate["phase"] == "gate" and gate["status"] == "queued" and gate["step"] == "Waiting on you"
    cap = gate["rows"][0]["cap_usd"]
    assert gate["totals"]["videos"] == 5 and gate["totals"]["cap_usd"] == round(5 * cap, 2)
    assert [r["video_id"] for r in gate["rows"]] == videos and {r["state"] for r in gate["rows"]} == {"planned"}
    assert {r["stage_label"] for r in gate["rows"]} == {"Draft"}
    # No turn history yet: the cost and time are left out, never guessed.
    assert gate["totals"]["est_usd"] is None and gate["totals"]["est_s"] is None
    assert fake.entered == [] and ledger.spent_usd_by_folder("f1") == 0
    picked = plan(client, video_ids=["p2", "p4"])
    assert [r["video_id"] for r in picked["rows"]] == ["p2", "p4"] and picked["totals"]["videos"] == 2
    listed = client.get("/projects/f1/batches").json()["batches"]
    assert [b["batch_id"] for b in listed] == [picked["batch_id"], gate["batch_id"]]
    assert client.post(f"/projects/f1/batches/{picked['batch_id']}/cancel").json()["status"] == "cancelled"


def test_five_videos_with_one_failure_finish_the_other_four_and_usage_is_the_sum_of_children(client, sample_video, monkeypatch):
    five(client, sample_video)
    fake = agent(monkeypatch, {"p3": [RuntimeError("the model fell over")]})
    before = ledger.spent_usd_by_folder("f1")
    gate = plan(client)
    started = client.post(f"/projects/f1/batches/{gate['batch_id']}/go")
    assert started.status_code == 202 and started.json()["phase"] == "running"
    assert client.post(f"/projects/f1/batches/{gate['batch_id']}/go").status_code == 409   # one Go only
    done = finished(client, gate["batch_id"])
    by = {r["video_id"]: r for r in done["rows"]}
    assert by["p3"]["state"] == "failed" and "fell over" in by["p3"]["why"]
    assert all(by[v]["state"] == "nothing" for v in ("p1", "p2", "p4", "p5"))
    assert done["status"] == "done" and done["phase"] == "finished"
    assert sorted(done["summary"]["finished"]) == ["p1", "p2", "p4", "p5"] and done["summary"]["failed"] == ["p3"]
    assert fake.most <= 3                                                    # three at a time
    # Usage: what the project spent is exactly what the children spent, and the parent says the same.
    spent = round(ledger.spent_usd_by_folder("f1") - before, 4)
    assert spent > 0 and done["spent_usd"] == pytest.approx(spent, abs=1e-4)
    assert done["summary"]["spent_usd"] == pytest.approx(spent, abs=1e-4)
    for v in ("p1", "p2", "p4", "p5"):
        assert by[v]["spent_usd"] == pytest.approx(ledger.spent_usd(v), abs=1e-4)
    # Each child is an Activity job in its own video, naming its parent.
    child = client.get("/videos/p1/jobs").json()["jobs"]
    assert any(j["kind"] == "batch" and j["detail"]["parent_id"] == gate["batch_id"] for j in child)
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert {"batch.planned", "batch.started", "batch.finished"} <= set(verbs)


def test_cancel_stops_the_queued_videos_and_the_running_ones_finish(client, sample_video, monkeypatch):
    five(client, sample_video)
    hold = threading.Event()
    fake = agent(monkeypatch, {}, gate=hold)
    gate = plan(client)
    client.post(f"/projects/f1/batches/{gate['batch_id']}/go")
    deadline = time.time() + 120
    while len(fake.entered) < 3 and time.time() < deadline:
        time.sleep(0.02)
    assert len(fake.entered) == 3
    cancelled = client.post(f"/projects/f1/batches/{gate['batch_id']}/cancel").json()
    states = {r["video_id"]: r["state"] for r in cancelled["rows"]}
    assert sorted(states.values()) == ["cancelled", "cancelled", "working", "working", "working"]
    hold.set()
    done = finished(client, gate["batch_id"])
    by = {r["video_id"]: r for r in done["rows"]}
    running = [v for v, s in states.items() if s == "working"]
    assert all(by[v]["state"] != "cancelled" and by[v]["state"] != "failed" for v in running)    # they finished
    assert sorted(v for v, r in by.items() if r["state"] == "cancelled") == sorted(set(states) - set(running))
    assert done["status"] == "cancelled" and done["phase"] == "cancelled"
    assert sorted(done["summary"]["cancelled"]) == sorted(set(states) - set(running))
    assert len(fake.entered) == 3                                              # the queued ones never asked Claude


def test_a_batch_above_the_project_ceiling_does_not_start(client, sample_video, monkeypatch):
    five(client, sample_video)
    agent(monkeypatch, {})
    client.patch("/projects/f1", json={"ceiling_usd": 0.05})
    resp = client.post("/projects/f1/batches", json={"goal": "Make it 30% off"})
    assert resp.status_code == 409
    assert "Spring" in resp.json()["detail"] and "$0.05 project ceiling" in resp.json()["detail"]
    assert "Raise the ceiling" in resp.json()["detail"]
    assert client.get("/projects/f1/batches").json()["batches"] == []


def test_a_video_with_a_question_pauses_alone_and_its_answer_carries_it_on(client, sample_video, monkeypatch):
    five(client, sample_video)
    agent(monkeypatch, {"p2": [reply(use("ask", "a1", **ASK), stop="tool_use")]})
    gate = plan(client)
    client.post(f"/projects/f1/batches/{gate['batch_id']}/go")
    done = finished(client, gate["batch_id"])
    by = {r["video_id"]: r for r in done["rows"]}
    assert by["p2"]["state"] == "waiting" and by["p2"]["label"] == "Waiting on you"
    assert by["p2"]["question"]["text"] == ASK["question"] and by["p2"]["question"]["options"] == ["30%", "25%"]
    assert all(by[v]["state"] == "nothing" for v in ("p1", "p3", "p4", "p5"))
    assert done["summary"]["waiting"] == ["p2"]
    answered = client.post(f"/projects/f1/batches/{gate['batch_id']}/videos/p2/answer", json={"text": "30%"})
    assert answered.status_code == 202, answered.text
    deadline = time.time() + 120
    row = None
    while time.time() < deadline:
        row = {r["video_id"]: r for r in client.get(f"/projects/f1/batches/{gate['batch_id']}").json()["rows"]}["p2"]
        if row["state"] != "working" and row["answers"] and row["answers"][0].get("status"):
            break
        time.sleep(0.05)
    assert row["state"] == "nothing" and row["answers"][0]["text"] == "30%"
    assert row["spent_usd"] == pytest.approx(ledger.spent_usd("p2"), abs=1e-4)   # both of its turns
    assert client.post(f"/projects/f1/batches/{gate['batch_id']}/videos/p1/answer", json={"text": "yes"}).status_code == 409


def test_bring_up_to_date_runs_as_a_batch_with_the_flag_on(client, sample_video, monkeypatch):
    from app.domain.models import Statement, Transcript, Word
    from tests.api.test_brief_update_api import ship, await_run
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1")
    repo.update_transcript("p2", Transcript(words=(Word("Welcome", 0.0, 0.5), Word("back", 0.5, 1.0)),
                                            statements=(Statement("Welcome back.", 0.0, 1.0),)))
    ship(client, "p1", "Get 20% off today")
    ship(client, "p2", "Welcome back")
    client.patch("/projects/f1", json={"brief": "Get 30% off."})
    agent(monkeypatch, {})
    run = client.post("/projects/f1/brief-update").json()["run"]
    assert run["batch_id"] and run["status"] == "gate"
    assert client.post(f"/projects/f1/batches/{run['batch_id']}/go").status_code == 202
    run = await_run(client)
    by = {v["video_id"]: v for v in run["videos"]}
    assert by["p2"]["outcome"] == "current" and "nothing was spent" in by["p2"]["why"]
    batch = client.get(f"/projects/f1/batches/{run['batch_id']}").json()
    assert batch["source"] == "brief" and batch["phase"] == "finished"
    assert {r["video_id"]: r["state"] for r in batch["rows"]}["p2"] == "nothing"
    plan_p2 = next(r for r in batch["rows"] if r["video_id"] == "p2")
    assert plan_p2["lines"] == 0 and plan_p2["est_usd"] == 0                  # nothing to run, nothing estimated


def test_the_routes_are_behind_the_batch_flag(client, sample_video, monkeypatch):
    five(client, sample_video)
    agent(monkeypatch, {})
    flags.set("projects.batch", "local", False)
    assert client.post("/projects/f1/batches", json={"goal": "x"}).status_code == 404
    assert client.get("/projects/f1/batches").status_code == 404
