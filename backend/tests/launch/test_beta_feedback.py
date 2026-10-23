"""Launch rehearsal item 11: "Send feedback" and the admins' list of it.

Sam sends a message with the route, his open video, his last job and a PNG
screenshot; the user agent is read from the request. A video that is not his
is dropped. The screenshot is sniffed (a PNG named .png that is really text is
refused) and capped; sending is rate limited. Admins list it newest first,
move its status (audited) and open the screenshot; everyone else gets 404.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import admin, auth, beta_feedback_api
from app.api.main import app, database, jobs, repo

H = {"X-Requested-With": "voltage"}
ADA, SAM, BO = "google:ada", "google:sam", "google:bo"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _client(sub: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": sub, "email": f"{sub}@example.com", "name": sub, "picture": None}, "s3cret"))
    return client


@pytest.fixture()
def world(monkeypatch, sample_video):
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret", admin_owners=(ADA,)))
    monkeypatch.setattr(beta_feedback_api, "sends", beta_feedback_api.RateLimit(10, 3600.0))
    repo.reset()
    jobs.reset()
    with database.tx() as c:
        c.execute("DELETE FROM beta_feedback")
    sam, bo = _client("sam"), _client("bo")
    with open(sample_video, "rb") as handle:
        made = sam.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H)
    assert made.status_code == 200, made.text
    video = made.json().get("video_id") or made.json()["project_id"]
    with open(sample_video, "rb") as handle:
        theirs = bo.post("/videos", files={"file": ("b.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H)
    yield {"sam": sam, "bo": bo, "ada": _client("ada"), "video": video,
           "bos_video": theirs.json().get("video_id") or theirs.json()["project_id"]}


def _send(client, **form):
    files = form.pop("files", None)
    return client.post("/beta-feedback", data=form, files=files, headers={**H, "User-Agent": "TestBrowser/1.0"})


def test_feedback_is_stored_with_its_context_and_screenshot(world):
    sam, video = world["sam"], world["video"]
    job = main.activity.create(video, "export")
    out = _send(sam, message="The Add button hid behind the pane.", route=f"#v/{video}", video_id=video, job_id=job.job_id,
                app_version="2026.11.04", files={"screenshot": ("shot.png", PNG, "image/png")})
    assert out.status_code == 201, out.text
    assert out.json()["said"] == beta_feedback_api.THANKS
    listed = world["ada"].get("/admin/beta-feedback").json()
    [item] = listed["items"]
    assert (item["owner"], item["route"], item["video_id"], item["job_id"], item["app_version"]) == \
        (SAM, f"#v/{video}", video, job.job_id, "2026.11.04")
    assert item["user_agent"] == "TestBrowser/1.0" and item["screenshot"] and item["status"] == "new"
    assert listed["counts"] == {"new": 1, "seen": 0, "done": 0}
    shot = world["ada"].get(f"/admin/beta-feedback/{item['id']}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png" and shot.content == PNG
    with database.tx() as c:
        ws = c.execute("SELECT workspace_id FROM beta_feedback").fetchone()[0]
    assert ws == main.members_store.workspace_of(database, SAM)


def test_a_message_is_required_and_others_ids_are_dropped(world):
    sam = world["sam"]
    assert _send(sam, message="  ").status_code == 422
    out = _send(sam, message="Hi", video_id=world["bos_video"], job_id="J999")
    assert out.status_code == 201
    [item] = world["ada"].get("/admin/beta-feedback").json()["items"]
    assert item["video_id"] is None and item["job_id"] is None and not item["screenshot"]


def test_the_screenshot_is_sniffed_and_capped(world, monkeypatch):
    sam = world["sam"]
    fake = _send(sam, message="x", files={"screenshot": ("shot.png", b"<svg onload=alert(1)>", "image/png")})
    assert fake.status_code == 415 and "PNG, JPEG or WebP" in fake.json()["detail"]
    monkeypatch.setattr(beta_feedback_api, "MAX_SCREENSHOT", 32)
    big = _send(sam, message="x", files={"screenshot": ("shot.png", PNG, "image/png")})
    assert big.status_code == 413
    assert world["ada"].get("/admin/beta-feedback").json()["items"] == []


def test_sending_is_rate_limited(world, monkeypatch):
    monkeypatch.setattr(beta_feedback_api, "sends", beta_feedback_api.RateLimit(2, 3600.0))
    assert [_send(world["sam"], message="m").status_code for _ in range(3)] == [201, 201, 429]


def test_admins_move_the_status_and_it_is_audited(world):
    _send(world["sam"], message="One")
    ada = world["ada"]
    [item] = ada.get("/admin/beta-feedback").json()["items"]
    with database.tx() as c:
        start = int(c.execute("SELECT COALESCE(MAX(id), 0) FROM admin_audit").fetchone()[0])
    moved = ada.put(f"/admin/beta-feedback/{item['id']}", json={"status": "seen"}, headers=H)
    assert moved.status_code == 200 and moved.json()["status"] == "seen" and moved.json()["status_by"] == ADA
    assert ada.put(f"/admin/beta-feedback/{item['id']}", json={"status": "maybe"}, headers=H).status_code == 422
    assert ada.get("/admin/beta-feedback", params={"status": "new"}).json()["items"] == []
    assert len(ada.get("/admin/beta-feedback", params={"status": "seen"}).json()["items"]) == 1
    [row] = [r for r in admin.recent_audit(database, target=SAM) if r["id"] > start]
    assert row["action"] == "feedback_status" and row["details"] == {"feedback_id": item["id"], "from": "new", "to": "seen"}


def test_only_admins_read_or_move_feedback(world):
    _send(world["sam"], message="Mine", files={"screenshot": ("s.png", PNG, "image/png")})
    [item] = world["ada"].get("/admin/beta-feedback").json()["items"]
    for client in (world["sam"], world["bo"]):
        assert client.get("/admin/beta-feedback").status_code == 404
        assert client.put(f"/admin/beta-feedback/{item['id']}", json={"status": "done"}, headers=H).status_code == 404
        assert client.get(f"/admin/beta-feedback/{item['id']}/screenshot").status_code == 404
    assert TestClient(app).post("/beta-feedback", data={"message": "x"}, headers=H).status_code == 401


def test_the_migration_goes_down_only_when_empty(tmp_path):
    from app.store import migrate
    from app.store.migrations import m0037_beta_feedback as m37
    conn = migrate.connect(str(tmp_path / "a.db"))
    migrate.up(conn)
    migrate.down_to(conn, 36)
    assert "beta_feedback" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    migrate.up(conn)
    conn.execute("INSERT INTO beta_feedback (owner, message, created_at) VALUES ('a', 'b', 't')")
    with pytest.raises(RuntimeError, match="refusing"):
        m37.down(conn)
    conn.close()


def test_the_sniffer_knows_the_screenshot_formats():
    from app.media import sniff
    assert sniff.image(PNG) == "png"
    assert sniff.image(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "jpg"
    assert sniff.image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    with pytest.raises(sniff.SniffError):
        sniff.image(b"GIF89a")
