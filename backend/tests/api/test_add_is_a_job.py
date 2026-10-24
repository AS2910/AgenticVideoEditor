"""Run 4, item 3: Add is a job. The approve route answers at once with the
render's job; the render runs on the work pool, like "Render now" and the
turn's preview, so no request ever holds a thread for a render."""
import threading
import time

from tests.api.test_endpoints import add, client, project, reset_state, voiced  # noqa: F401
from tests.api.test_jobs import wait_job


def test_add_returns_at_once_with_a_render_job_and_the_job_renders(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch)
    plan_id = done["plan"]["plan_id"]
    gate = threading.Event()
    real = main._render_now

    def held(*a, **kw):
        assert gate.wait(30), "the render was never let go"
        return real(*a, **kw)
    monkeypatch.setattr(main, "_render_now", held)

    started = time.time()
    resp = client.post(f"/videos/p1/plans/{plan_id}/approve", json={})
    took = time.time() - started
    body = resp.json()
    assert resp.status_code == 200 and took < 5                    # the render is still held: the answer did not wait
    assert [a["edit_id"] for a in body["approved"]] == ["e1"] and body["export"] is None
    assert body["plan"]["items"][0]["status"] == "approved"        # the added line is in at once
    job = body["render_job"]
    assert job["kind"] == "render_preview" and job["status"] in ("queued", "running")
    assert job["detail"]["mode"] == "final" and job["detail"]["added"] is True and job["line_ids"] == ["e1"]
    # The status strip and the rows read it like any job.
    assert any(j["job_id"] == job["job_id"] for j in client.get("/videos/p1/jobs?active=1").json()["jobs"])

    gate.set()
    finished = wait_job(client, job["job_id"])
    assert finished["status"] == "done" and finished["detail"]["version"] >= 1
    latest = client.get("/videos/p1/renders/latest?mode=final").json()["latest"]
    assert latest["version"] == finished["detail"]["version"]
    assert [s["kind"] for s in latest["manifest"]["segments"]] == ["edited"]
    assert client.get(f"/videos/p1/plans/{plan_id}").json()["log"][-1]["text"] == "Rendered the edited video"


def test_a_failed_add_render_fails_its_job_with_a_reason_and_the_line_stays_added(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch)

    def broken(*a, **kw):
        raise RuntimeError("ffmpeg ran out of room")
    monkeypatch.setattr(main, "_render_now", broken)

    body = client.post(f"/videos/p1/plans/{done['plan']['plan_id']}/approve", json={}).json()
    failed = wait_job(client, body["render_job"]["job_id"])
    assert failed["status"] == "failed" and failed["error_code"] == "render_failed"
    assert "ffmpeg ran out of room" in failed["error_text"] and failed["retryable"] is True
    assert [e["edit_id"] for e in client.get("/videos/p1").json()["edits"]] == ["e1"]

    monkeypatch.undo()
    retried = client.post(f"/videos/p1/jobs/{failed['job_id']}/retry").json()
    assert wait_job(client, retried["job_id"])["status"] == "done"


def test_nothing_added_starts_no_render(client, project, monkeypatch):
    done = voiced(client, monkeypatch)
    body = client.post(f"/videos/p1/plans/{done['plan']['plan_id']}/approve", json={"items": ["nope"]}).json()
    assert body["approved"] == [] and body["render_job"] is None and body["export"] is None


def test_the_agents_own_ship_still_renders_in_line(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch)
    shipped = main._ship("p1", main.repo.get("p1"), done["plan"]["plan_id"], None)
    assert shipped["export"] is not None and shipped["render_job"] is None
