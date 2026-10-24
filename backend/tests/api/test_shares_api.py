"""F6 through the API: the owner makes, lists and turns off links on a
project; anyone holding a live link reads what it shares with no account,
plays or downloads the file; an expired or turned-off link is refused with
a sentence, never a bare error."""
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, flags, jobs, repo
from app.media import ffmpeg
from app.store import shares
from tests.api.test_folders import upload_into
from tests.factories import export_now  # noqa: E402

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.batch", "local")
    flags.clear("projects.review", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def test_a_project_link_lists_every_rendered_video_and_serves_it(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1", name="ad1.mp4")
    upload_into(client, sample_video, "f1", name="ad2.mp4")
    assert export_now(client, "/videos/p1/export", json={"purpose": "export"}).status_code == 200    # p2 never rendered
    made = client.post("/projects/f1/shares", json={"scope": "project"})
    assert made.status_code == 201, made.text
    link = made.json()
    assert link["state"] == "live" and link["role"] == "viewer" and "/#s/" in link["url"]
    token = link["url"].split("/#s/")[1]
    opened = client.get(f"/share/{token}")
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["title"] == "Spring" and body["scope"] == "project" and len(body["files"]) == 1
    f = body["files"][0]
    assert f["video_id"] == "p1" and f["name"] == "ad1-voltage.mp4" and "path" not in f
    played = client.get(f"/share/{token}/files/{f['file_id']}")
    assert played.status_code == 200 and played.headers["content-type"] == "video/mp4"
    assert played.headers["content-disposition"].startswith("inline")
    got = client.get(f"/share/{token}/files/{f['file_id']}?download=true")
    assert got.headers["content-disposition"].startswith("attachment") and len(got.content) == f["size"]
    assert client.get(f"/share/{token}/files/nope").status_code == 404
    assert [s["share_id"] for s in client.get("/projects/f1/shares").json()["shares"]] == [link["share_id"]]


def test_a_turned_off_or_expired_link_is_refused_with_a_clear_message(client, sample_video, monkeypatch):
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1", name="ad1.mp4")
    link = client.post("/projects/f1/shares", json={"scope": "video", "target": "p1", "days": 2}).json()
    token = link["url"].split("/#s/")[1]
    assert client.get(f"/share/{token}").json()["files"] == []           # nothing rendered yet: an empty list
    monkeypatch.setattr(shares, "now_iso", lambda: "2999-01-01T00:00:00.000Z")
    expired = client.get(f"/share/{token}")
    assert expired.status_code == 410 and expired.json()["detail"] == shares.REFUSED["expired"]
    monkeypatch.undo()
    off = client.delete(f"/projects/f1/shares/{link['share_id']}")
    assert off.status_code == 200 and off.json()["state"] == "revoked"
    refused = client.get(f"/share/{token}")
    assert refused.status_code == 410 and refused.json()["detail"] == shares.REFUSED["revoked"]
    assert refused.headers["x-share-refused"] == "revoked"
    bad = client.get("/share/sh00.nope")
    assert bad.status_code == 404 and bad.json()["detail"] == shares.REFUSED["invalid"]
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert {"share.created", "share.revoked"} <= set(verbs)


def test_a_link_to_a_deleted_project_is_gone(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    token = client.post("/projects/f1/shares", json={"scope": "project"}).json()["url"].split("/#s/")[1]
    client.delete("/projects/f1?videos=delete")
    gone = client.get(f"/share/{token}")
    assert gone.status_code == 404 and gone.json()["detail"] == shares.REFUSED["gone"]


def test_targets_are_checked_and_links_need_the_flag(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    client.post("/projects", json={"name": "Other"})
    upload_into(client, sample_video, "f2", name="elsewhere.mp4")
    assert client.post("/projects/f1/shares", json={"scope": "video", "target": "p1"}).status_code == 404
    assert client.post("/projects/f1/shares", json={"scope": "project", "target": "f2"}).status_code == 422
    assert client.post("/projects/f1/shares", json={"scope": "project", "days": 0}).status_code == 422
    assert client.delete("/projects/f1/shares/sh-none").status_code == 404
    flags.set("projects.batch", "local", False)
    flags.set("projects.review", "local", False)
    assert client.post("/projects/f1/shares", json={"scope": "project"}).status_code == 404
    assert client.get("/projects/f1/shares").status_code == 404


def test_the_server_key_is_kept_in_the_data_dir():
    assert (main.settings.data_dir / shares.SECRET_FILE).exists() or main.settings.share_secret
