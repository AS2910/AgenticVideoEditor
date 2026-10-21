"""A1 through the API: a shipped edit records the brief it was made with, a
brief change marks older videos "Brief changed" (moves in and out counted),
and Bring up to date runs each stale video in turn, marking one the change
does not touch current without spending."""
import time

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, database, flags, jobs, ledger, repo
from app.domain.models import Statement, Transcript, Word
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, generate
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


def ship(client, video_id, text="30% off"):
    candidate = generate(text=text, project_id=video_id)
    return client.post(f"/videos/{video_id}/edits", json={"candidate_id": candidate["candidate_id"]}).json()


def stale_ids(client, project_id="f1"):
    return [v["video_id"] for v in client.get(f"/projects/{project_id}").json()["videos"] if v["brief_changed"]]


def await_run(client, project_id="f1", timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/projects/{project_id}/brief-update").json()["run"]
        if run and run["status"] == "finished" and run.get("finished_at"):
            return run
        time.sleep(0.05)
    raise AssertionError("the run never finished")


def test_shipping_records_the_brief_and_a_change_marks_older_videos(client, sample_video):
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1")
    assert stale_ids(client) == []
    ship(client, "p1")
    assert repo.get("p1").made_with_brief == 1 and repo.get("p2").made_with_brief is None
    page = client.patch("/projects/f1", json={"brief": "Get 30% off."}).json()
    assert page["brief_version"] == 2 and page["stale_count"] == 1
    assert page["brief_edited_by"] == "local" and page["brief_edited_at"]
    assert stale_ids(client) == ["p1"]                                     # p2 shipped nothing: never stale
    video = client.get("/videos/p1").json()
    assert video["brief_changed"] and video["made_with_brief"] == 1 and video["brief_version"] == 2
    assert any(v["brief_changed"] for v in client.get("/videos").json()["videos"])   # Home's cards
    ship(client, "p1")                                                     # a hand Add it: the current version
    assert repo.get("p1").made_with_brief == 2 and stale_ids(client) == []


def test_the_stale_count_follows_a_move_out_and_in(client, sample_video):
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    client.post("/projects", json={"name": "Autumn", "brief": "Warm."})
    upload_into(client, sample_video, "f1")
    ship(client, "p1")
    client.patch("/projects/f1", json={"brief": "Get 30% off."})
    assert client.get("/projects/f1").json()["project"]["stale_count"] == 1
    client.patch("/videos/p1", json={"project_id": None})                 # out: standalone, never stale
    assert client.get("/projects/f1").json()["project"]["stale_count"] == 0
    assert client.get("/videos/p1").json()["brief_changed"] is False
    client.patch("/videos/p1", json={"project_id": "f2"})                 # in, with edits: made before this brief
    assert client.get("/projects/f2").json()["project"]["stale_count"] == 1 and stale_ids(client, "f2") == ["p1"]


def test_bring_up_to_date_skips_an_untouched_video_for_free_and_runs_a_turn_on_the_other(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1")
    repo.update_transcript("p2", Transcript(words=(Word("Welcome", 0.0, 0.5), Word("back", 0.5, 1.0)),
                                            statements=(Statement("Welcome back.", 0.0, 1.0),)))
    ship(client, "p1", "Get 20% off today")
    ship(client, "p2", "Welcome back")
    client.patch("/projects/f1", json={"brief": "Get 30% off."})
    assert sorted(stale_ids(client)) == ["p1", "p2"]
    scripted = _agent_on(monkeypatch, main, [reply(text("The offer line already reads right here; nothing to change."))])
    spent_p2 = ledger.spent_usd("p2")
    run = client.post("/projects/f1/brief-update").json()["run"]
    assert run["to"] == 2 and [v["video_id"] for v in run["videos"]] == ["p1", "p2"]
    # Decision 0: the press opens the normal batch gate; nothing runs or is spent until Go.
    assert run["status"] == "gate" and run["gate"]["phase"] == "gate" and run["gate"]["totals"]["videos"] == 2
    assert len(scripted.calls) == 0
    again = client.post("/projects/f1/brief-update")                       # pressed again: a fresh gate, never a second run
    assert again.status_code == 202 and again.json()["run"]["batch_id"] != run["batch_id"]
    run = again.json()["run"]
    assert client.post(f"/projects/f1/batches/{run['batch_id']}/go").status_code == 202
    assert client.post("/projects/f1/brief-update").status_code == 409     # running: no second run
    run = await_run(client)
    by = {v["video_id"]: v for v in run["videos"]}
    assert by["p2"]["outcome"] == "current" and "nothing was spent" in by["p2"]["why"]
    assert ledger.spent_usd("p2") == spent_p2                             # no model call for p2
    assert len(scripted.calls) == 1 and "Apply brief changes v1 to v2" in str(scripted.calls[0]["messages"])
    assert by["p1"]["status"] == "done" and by["p1"]["outcome"] == "current"
    assert stale_ids(client) == [] and client.get("/projects/f1").json()["project"]["stale_count"] == 0
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert "brief.video_current" in verbs and "brief.update_started" in verbs and "brief.update_finished" in verbs
    assert client.post("/projects/f1/brief-update").status_code == 409     # nothing left to bring up to date


def test_the_routes_are_behind_the_consistency_flag(client):
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    assert client.get("/projects/f1/brief-update").json() == {"run": None}
    flags.set("projects.consistency", "local", False)
    assert client.get("/projects/f1/brief-update").status_code == 404
    assert client.post("/projects/f1/brief-update").status_code == 404
    assert database is not None


def test_bring_up_to_date_shows_the_gate_without_the_batch_flag(client, sample_video, monkeypatch):
    """Decision 0: the public launch has A1 on and Phase B off; the gate and its Go still work."""
    import app.api.main as main
    from tests.agent.conftest import reply, text
    flags.set("projects.batch", "local", False)
    try:
        client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
        upload_into(client, sample_video, "f1")
        ship(client, "p1", "Get 20% off today")
        client.patch("/projects/f1", json={"brief": "Get 30% off."})
        _agent_on(monkeypatch, main, [reply(text("Nothing to change."))])
        run = client.post("/projects/f1/brief-update").json()["run"]
        assert run["status"] == "gate" and run["gate"]["rows"][0]["video_id"] == "p1"
        assert client.post("/projects/f1/batches").status_code in (404, 405, 422)   # other batches stay off
        assert client.post(f"/projects/f1/batches/{run['batch_id']}/go").status_code == 202
        assert await_run(client)["videos"][0]["status"] == "done"
    finally:
        flags.clear("projects.batch", "local")


def test_cancel_at_the_gate_ends_the_run_without_spending(client, sample_video):
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    upload_into(client, sample_video, "f1")
    ship(client, "p1", "Get 20% off today")
    client.patch("/projects/f1", json={"brief": "Get 30% off."})
    run = client.post("/projects/f1/brief-update").json()["run"]
    assert client.post(f"/projects/f1/batches/{run['batch_id']}/cancel").status_code == 200
    after = client.get("/projects/f1/brief-update").json()["run"]
    assert after["status"] == "finished" and stale_ids(client) == ["p1"]
