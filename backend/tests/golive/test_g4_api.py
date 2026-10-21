"""G4 through the API: the bell lists what happened and marks it read;
jobs notify only when they fail or run long (never each line); review news
lands in the bell and the digest; spend alerts at 50/80/100% of a ceiling,
once each; per-person settings; the flag off keeps C2's digest as it was."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import activity, app, database, flags, jobs, ledger, repo
from app.media import ffmpeg
from app.notify import digest
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("golive.g4", "local")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def video(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    return "p1"


def bell(client):
    return client.get("/me/notifications").json()




@pytest.fixture()
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(activity, "clock", lambda: now[0])
    return now


def test_jobs_notify_on_failure_and_long_finishes_only(client, video, clock):
    # A short export: nothing. A long one: done. A failed check: failed. A line in a turn: nothing.
    for secs, kind in ((5, "export"), (90, "export")):
        job = activity.create(video, kind)
        activity.start(job.job_id)
        clock[0] += secs
        activity.finish(job.job_id, step_label="v3 ready")
    failed = activity.create("f1", "check")
    activity.start(failed.job_id)
    activity.fail(failed.job_id, "check_failed", "The check stopped: no transcript.")
    line = activity.create(video, "voice_line", turn_id="j1")
    activity.start(line.job_id)
    activity.fail(line.job_id, "vendor_failed", "ElevenLabs said no.")
    child = activity.create(video, "export", detail={"parent_id": "J1"})
    activity.start(child.job_id)
    activity.fail(child.job_id, "render_failed", "x")
    page = bell(client)
    assert [(i["kind"], i["title"], i["link"]) for i in page["items"]] == [
        ("job_failed", "The project check of Diwali failed.", "#p/f1"),
        ("job_done", "The export of ad.mp4 is done.", f"#v/{video}"),
    ]
    assert page["unread"] == 2 and page["items"][0]["body"] == "The check stopped: no transcript."


def test_read_marks_and_settings(client, video):
    for n in range(3):
        main.inbox.add(database, "local", "job_failed", f"Failed {n}.")
    ids = [i["id"] for i in bell(client)["items"]]
    assert client.post("/me/notifications/read", json={"ids": ids[:1]}).json() == {"unread": 2}
    assert client.get("/me/notifications/count").json() == {"unread": 2}
    assert client.post("/me/notifications/read", json={"all": True}).json() == {"unread": 0}
    kinds = client.put("/me/notifications/settings", json={"job_failed": {"in_app": False}}).json()["kinds"]
    assert next(k for k in kinds if k["kind"] == "job_failed")["in_app"] is False
    failed = activity.create("f1", "check")
    activity.start(failed.job_id)
    activity.fail(failed.job_id, "x", "no")
    assert bell(client)["unread"] == 0                                  # in the app: off
    assert [p["kind"] for p in digest.pending(database, "local")] == ["job_failed"] * 4   # email: still on
    assert client.put("/me/notifications/settings", json={"nope": {}}).status_code == 422


def test_spend_alerts_once_each_at_50_80_and_100(client, video):
    client.patch("/projects/f1", json={"ceiling_usd": 1.0})
    for usd in (0.3, 0.25, 0.05, 0.25, 0.1, 0.2):          # 0.30, 0.55, 0.60, 0.85, 0.95, 1.15
        ledger.record(video, "anthropic", "turn", 1, "tokens", usd)
    project = [i["title"] for i in bell(client)["items"] if i["link"] == "#p/f1"]
    assert project == ["You have reached the ceiling of Diwali ($1). Paid steps stop until it is raised.",
                       "You have used 80% of the ceiling of Diwali ($0.85 of $1).",
                       "You have used 50% of the ceiling of Diwali ($0.55 of $1)."]
    video_alerts = [i["title"] for i in bell(client)["items"] if i["link"] == f"#v/{video}"]
    assert video_alerts == ["You have used 50% of the ceiling of ad.mp4 ($1.15 of $2)."]   # the $2 video ceiling


def test_review_news_reaches_the_bell_and_the_digest(client, video, monkeypatch):
    monkeypatch.setattr(main, "_check_reader", None)
    share = client.post(f"/videos/{video}/review-links", json={"name": "Priya"}).json()
    token = share["token"] if "token" in share else share["url"].rsplit("/", 1)[-1]
    said = client.post(f"/share/{token}/comments", json={"video_id": video, "at_s": 1.0, "text": "Louder.", "version": None})
    assert said.status_code == 201, said.text
    client.post(f"/share/{token}/approve", json={"video_id": video})
    items = bell(client)["items"]
    assert [i["kind"] for i in items] == ["approval", "review_comment"]
    assert items[1]["title"] == "Priya commented on ad.mp4 at 0:01." and items[1]["link"] == f"#v/{video}@1.0"
    assert [p["kind"] for p in digest.pending(database, "local")] == ["comment", "approved"]   # emailed as before


def test_the_flag_off_keeps_the_review_digest_and_hides_the_bell(client, video):
    flags.set("golive.g4", "local", False)
    assert client.get("/me/notifications").status_code == 404
    failed = activity.create("f1", "check")
    activity.start(failed.job_id)
    activity.fail(failed.job_id, "x", "no")
    with database.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
