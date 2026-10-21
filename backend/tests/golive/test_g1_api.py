"""G1 through the API: the sample project is made once per new owner (with
the recorded run, no charge), is deletable and never comes back; an import
from a link is an Activity job that downloads (HTTP mocked), sniffs and
lands as an ordinary video, or fails with a sentence."""
import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, flags, jobs, ledger, repo
from app.media import ffmpeg
from app.tutorial import sample

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    repo.reset()
    jobs.reset()
    monkeypatch.setattr(main, "IMPORT_IN_BACKGROUND", False)
    yield
    flags.clear("golive.g1", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def test_a_new_owner_gets_the_sample_project_once(client):
    made = client.post("/me/sample").json()
    assert made["created"] is True
    [project] = client.get("/projects").json()["projects"]
    assert project["name"] == sample.NAME and project["sample"] is True and project["video_count"] == 1
    page = client.get(f"/projects/{project['project_id']}").json()
    [video] = page["videos"]
    assert client.get(f"/videos/{video['video_id']}/settings").json()["settings"].get("tutorial") is True   # the recorded run
    assert client.post("/me/sample").json() == {"created": False, "project_id": project["project_id"]}
    assert len(client.get("/projects").json()["projects"]) == 1
    assert ledger.spent_usd_by_folder(project["project_id"]) == 0


def test_a_deleted_sample_never_comes_back(client):
    pid = client.post("/me/sample").json()["project_id"]
    assert client.delete(f"/projects/{pid}?videos=delete").status_code in (200, 204)
    assert client.post("/me/sample").json()["created"] is False
    assert client.get("/projects").json()["projects"] == []


def test_an_owner_with_work_of_their_own_gets_no_sample(client):
    client.post("/projects", json={"name": "Mine"})
    assert client.post("/me/sample").json() == {"created": False, "project_id": None}
    client.delete("/projects/f1?videos=delete")
    assert client.post("/me/sample").json()["created"] is False     # decided once


def test_sample_needs_the_flag_and_is_per_owner(client):
    flags.set("golive.g1", "local", False)
    assert client.post("/me/sample").json()["created"] is False
    assert sample.ensure("someone-else")["created"] is False         # flag off for them by default
    flags.set("golive.g1", "someone-else", True)
    try:
        assert sample.ensure("someone-else")["created"] is True
        assert [p.name for p in repo.list_projects("someone-else")] == [sample.NAME]
        assert repo.list_projects("local") == []
    finally:
        flags.clear("golive.g1", "someone-else")


def serve(monkeypatch, handler):
    monkeypatch.setattr(main, "_link_http", httpx.Client(transport=httpx.MockTransport(handler)))


def test_import_from_a_dropbox_link_lands_as_a_video_in_the_project(client, monkeypatch, sample_video):
    body = sample_video.read_bytes()
    asked = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, content=body, headers={"content-type": "application/octet-stream",
                                                          "content-disposition": 'attachment; filename="spring.mp4"'})
    serve(monkeypatch, handler)
    folder = client.post("/projects", json={"name": "Spring"}).json()["project_id"]
    out = client.post("/imports", json={"url": "https://www.dropbox.com/s/abc/spring.mp4?dl=0", "project_id": folder})
    assert out.status_code == 202, out.text
    job = client.get(f"/imports/{out.json()['job_id']}").json()
    assert job["kind"] == "import" and job["status"] == "done", job
    assert "owner" not in job["detail"] and job["detail"]["source"] == "dropbox"
    assert asked == ["https://www.dropbox.com/s/abc/spring.mp4?dl=1"]
    video = client.get(f"/videos/{job['detail']['video_id']}").json()
    assert video["filename"] == "spring.mp4" and video["project_id"] == folder
    assert [j["job_id"] for j in client.get("/imports").json()["imports"]] == [job["job_id"]]


def test_a_failed_import_says_why_on_its_job(client, monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(200, content=b"<html>Sign in</html>", headers={"content-type": "text/html"}))
    out = client.post("/imports", json={"url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"}).json()
    assert out["status"] == "failed" and out["error_code"] == "import_failed"
    assert out["error_text"].startswith("That link opens a page on Google Drive")
    assert repo.list("local") == []


def test_links_that_cannot_work_are_refused_before_a_job(client):
    yt = client.post("/imports", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert yt.status_code == 422 and "connect your Google account" in yt.json()["detail"]
    assert client.post("/imports", json={"url": "https://example.com/a.mp4"}).status_code == 422
    assert client.get("/imports").json()["imports"] == []
    sources = client.get("/imports/sources").json()["sources"]
    assert [(s["name"], s["enabled"]) for s in sources] == [("drive", True), ("dropbox", True), ("youtube", False)]


def test_imports_need_the_flag_and_are_the_owners_own(client, monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(404))
    job = client.post("/imports", json={"url": "https://www.dropbox.com/s/abc/a.mp4"}).json()
    assert job["status"] == "failed" and "does not exist" in job["error_text"]
    other = main.activity.create("user-x", "import", detail={"owner": "x"})
    assert client.get(f"/imports/{other.job_id}").status_code == 404
    flags.set("golive.g1", "local", False)
    assert client.post("/imports", json={"url": "https://www.dropbox.com/s/abc/a.mp4"}).status_code == 404
