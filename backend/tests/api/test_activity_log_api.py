"""F7 through the API: shipping, undoing and moving a video are logged and
listed per project and per video, newest first, a page at a time."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import generate, upload

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def test_the_feed_shows_what_happened_newest_first(client, sample_video):
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    upload(client, sample_video)
    assert client.patch("/videos/p1", json={"project_id": "f1"}).status_code == 200
    candidate = generate(project_id="p1")
    edit = client.post("/videos/p1/edits", json={"candidate_id": candidate["candidate_id"]}).json()
    assert client.post(f"/videos/p1/edits/{edit['edit_id']}/revert").status_code == 200
    client.post("/projects/f1/rules", json={"kind": "banned", "data": {"word": "cheap"}})
    feed = client.get("/projects/f1/events").json()
    assert [e["verb"] for e in feed["events"]] == ["rule.added", "edit.undone", "edit.shipped", "video.moved_in", "brief.saved"]
    assert {e["actor_kind"] for e in feed["events"]} == {"user"} and feed["next"] is None
    page = client.get("/projects/f1/events", params={"limit": 2}).json()
    assert len(page["events"]) == 2 and page["next"]
    rest = client.get("/projects/f1/events", params={"limit": 10, "before": page["next"]}).json()
    assert [e["verb"] for e in rest["events"]] == ["edit.shipped", "video.moved_in", "brief.saved"]
    mine = client.get("/videos/p1/events/log").json()
    assert [e["verb"] for e in mine["events"]] == ["edit.undone", "edit.shipped", "video.moved_in"]
    client.patch("/videos/p1", json={"project_id": None})
    assert client.get("/projects/f1/events", params={"limit": 1}).json()["events"][0]["verb"] == "video.moved_out"
    assert client.get("/projects/f9/events").status_code == 404
    assert client.get("/videos/p9/events/log").status_code == 404
