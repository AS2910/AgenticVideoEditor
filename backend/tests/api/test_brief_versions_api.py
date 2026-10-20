"""F2 through the API: the project's PATCH saves a version, accepting a
suggestion does too, the versions and their diff are listed, and a turn
records the brief version its opening view read."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, await_job
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


def test_patching_the_brief_makes_versions_listed_newest_first_with_a_diff(client):
    made = client.post("/projects", json={"name": "Spring", "brief": "Price first."}).json()
    assert made["brief_version"] == 1
    changed = client.patch("/projects/f1", json={"brief": "Price first, then the date."}).json()
    assert changed["brief"] == "Price first, then the date." and changed["brief_version"] == 2
    client.patch("/projects/f1", json={"name": "Spring sale"})               # no new version
    listed = client.get("/projects/f1/briefs").json()
    assert listed["current"] == 2 and [v["version"] for v in listed["versions"]] == [2, 1]
    assert listed["versions"][0]["created_by"] == "local"
    diff = client.get("/projects/f1/briefs/diff", params={"a": 1, "b": 2}).json()
    assert {"op": "added", "text": ", then the date."} in diff["changes"] or any(r["op"] == "added" for r in diff["changes"])
    assert client.get("/projects/f1/briefs/diff", params={"a": 1, "b": 9}).status_code == 404
    assert client.get("/projects/f9/briefs").status_code == 404


def test_accepting_a_suggestion_is_a_new_version(client, sample_video):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    upload_into(client, sample_video, "f1")
    main._suggest_brief("p1", "Say the price first.", "")
    page = client.post("/projects/f1/suggestions/s1/accept").json()
    assert page["project"]["brief"] == "Bright.\nSay the price first." and page["project"]["brief_version"] == 2


def test_a_turn_records_the_brief_version_it_read(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    client.patch("/projects/f1", json={"brief": "Bright and short."})
    upload_into(client, sample_video, "f1")
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(text("Hello."))])
    job = await_job(client, client.post("/videos/p1/turns", json={"text": "hi"}).json()["job_id"])
    assert job["status"] == "succeeded"
    assert repo.settings("p1")["last_turn"]["brief_version"] == 2
    assert repo.settings("p1")["turn_view"]["brief_version"] == 2
    assert main.repo.turns("p1")[0]["content"][0]["text"].startswith("Brief · Spring: Bright and short.")
