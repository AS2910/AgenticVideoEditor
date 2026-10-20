"""F3 through the API, and the rules in a turn's opening view."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, await_job, upload
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def test_rules_crud(client):
    client.post("/projects", json={"name": "Spring"})
    made = client.post("/projects/f1/rules", json={"kind": "banned", "data": {"word": "cheap"}})
    assert made.status_code == 201 and made.json()["version"] == 1
    rid = made.json()["rule_id"]
    assert client.post("/projects/f1/rules", json={"kind": "banned", "data": {}}).status_code == 422
    changed = client.patch(f"/projects/f1/rules/{rid}", json={"data": {"word": "cheapest"}}).json()
    assert changed["version"] == 2 and changed["data"] == {"word": "cheapest"}
    listed = client.get("/projects/f1/rules").json()
    assert listed["rules_version"] == 2 and [r["rule_id"] for r in listed["rules"]] == [rid]
    assert client.delete(f"/projects/f1/rules/{rid}").status_code == 204
    assert client.delete(f"/projects/f1/rules/{rid}").status_code == 404
    assert client.patch("/projects/f1/rules/99", json={"data": {"word": "x"}}).status_code == 404
    assert client.get("/projects/f9/rules").status_code == 404


def test_the_rules_are_in_the_opening_view_of_a_video_in_the_project(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    client.post("/projects/f1/rules", json={"kind": "required_line", "data": {"text": "T&C apply"}})
    upload_into(client, sample_video, "f1")
    upload(client, sample_video, name="alone.mp4")
    for vid in ("p1", "p2"):
        client.put(f"/videos/{vid}/settings", json={"autonomy": "draft"})
        _agent_on(monkeypatch, main, [reply(text("Hello."))])
        assert await_job(client, client.post(f"/videos/{vid}/turns", json={"text": "hi"}).json()["job_id"])["status"] == "succeeded"
    head = main.repo.turns("p1")[0]["content"][0]["text"]
    assert "Every video in this project carries these lines: “T&C apply”.\nThe clip: ad.mp4" in head
    assert "carries these lines" not in main.repo.turns("p2")[0]["content"][0]["text"]

