"""B1 through the API, the main flow: ask across the project's videos, one
gate, Go, a board where one video has lines ready, one has nothing to
change and one failed; Add all that passed adds the passing lines in that
video only (its own add), and its one undo puts them back as proposals.
Claude is scripted per video and the voice is the mock (no spend)."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, flags, jobs, repo
from app.media import ffmpeg
from tests.agent.conftest import reply, text
from tests.api.test_batch_api import agent, finished
from tests.api.test_endpoints import take
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.batch", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def live_edits(video_id):
    return [e for e in repo.list_edits(video_id) if not e.reverted]


def test_ask_go_board_add_all_that_passed_and_undo_one_video(client, sample_video, monkeypatch):
    client.post("/projects", json={"name": "Spring", "brief": "Get 20% off."})
    for i in range(1, 4):
        upload_into(client, sample_video, "f1", name=f"ad{i}.mp4")
    agent(monkeypatch, {
        "p1": [reply(take(), stop="tool_use"), reply(text("The offer line is ready to hear."))],
        "p3": [RuntimeError("the model fell over")],
    })
    gate = client.post("/projects/f1/batches", json={"goal": "Make the offer 30% off"}).json()
    assert client.post(f"/projects/f1/batches/{gate['batch_id']}/add-all").status_code == 409     # nothing has run
    client.post(f"/projects/f1/batches/{gate['batch_id']}/go")
    board = finished(client, gate["batch_id"])
    by = {r["video_id"]: r for r in board["rows"]}
    assert by["p1"]["state"] == "ready" and by["p1"]["label"] == "Ready to review" and by["p1"]["ready"] == 1
    assert by["p2"]["state"] == "nothing" and by["p3"]["state"] == "failed"
    assert live_edits("p1") == []                                           # a batch never adds by itself
    added = client.post(f"/projects/f1/batches/{gate['batch_id']}/add-all")
    assert added.status_code == 200, added.text
    by = {r["video_id"]: r for r in added.json()["rows"]}
    assert by["p1"]["state"] == "added" and len(by["p1"]["added"]["edit_ids"]) == 1
    assert len(live_edits("p1")) == 1 and live_edits("p2") == [] and live_edits("p3") == []
    undone = client.post(f"/projects/f1/batches/{gate['batch_id']}/videos/p1/undo-add")
    assert undone.status_code == 200
    by = {r["video_id"]: r for r in undone.json()["rows"]}
    assert live_edits("p1") == [] and by["p1"]["state"] == "ready" and by["p1"]["added"]["undone_at"]
    assert client.post(f"/projects/f1/batches/{gate['batch_id']}/videos/p1/undo-add").status_code == 409   # one undo
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert {"batch.added_all", "batch.add_undone", "edit.shipped", "edit.undone"} <= set(verbs)


def test_fix_in_all_from_the_check_plans_the_issue_in_its_videos(client, sample_video, monkeypatch):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring"})
    for i in range(1, 4):
        upload_into(client, sample_video, "f1", name=f"ad{i}.mp4")
    agent(monkeypatch, {})
    issue = {"kind": "fact", "message": "The videos give different percentages.", "fingerprint": "fp1",
             "places": [{"video_id": "p1", "filename": "ad1.mp4", "t": 1.0, "text": "Get 20% off."},
                        {"video_id": "p3", "filename": "ad3.mp4", "t": 2.0, "text": "Get 30% off."}]}
    monkeypatch.setattr(main, "_issue_or_404", lambda project_id, issue_id: {**issue, "issue_id": issue_id})
    gate = client.post("/projects/f1/batches", json={"source": "fix", "issue_id": 7})
    assert gate.status_code == 201, gate.text
    body = gate.json()
    assert body["source"] == "fix" and [r["video_id"] for r in body["rows"]] == ["p1", "p3"]
    assert [r["lines"] for r in body["rows"]] == [1, 1] and body["phase"] == "gate"
