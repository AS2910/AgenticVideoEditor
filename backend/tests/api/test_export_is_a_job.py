"""Run 4, item 3d: POST /videos/{id}/export never renders. A render that is not
made yet comes back as 202 with its job; asked again once the job is done, the
route answers with the render, as it always did."""
import threading

from tests.api.test_endpoints import client, project, reset_state, voiced  # noqa: F401
from tests.api.test_jobs import wait_job


def test_an_export_not_made_yet_is_a_job_and_asking_again_reads_the_render(client, project, monkeypatch):
    import app.api.main as main
    gate = threading.Event()
    real = main._render_now

    def held(*a, **kw):
        assert gate.wait(30), "the render was never let go"
        return real(*a, **kw)
    monkeypatch.setattr(main, "_render_now", held)

    first = client.post("/videos/p1/export", json={"request_id": 7})
    assert first.status_code == 202 and first.json()["request_id"] == 7
    job = first.json()["render_job"]
    assert job["kind"] == "render_preview" and job["status"] in ("queued", "running") and job["detail"]["mode"] == "final"
    # Asked again while it runs: the same job, not a second render.
    again = client.post("/videos/p1/export", json={"request_id": 8})
    assert again.status_code == 202 and again.json()["render_job"]["job_id"] == job["job_id"]

    gate.set()
    assert wait_job(client, job["job_id"])["status"] == "done"
    made = client.post("/videos/p1/export", json={"request_id": 9})
    assert made.status_code == 200
    body = made.json()
    assert body["request_id"] == 9 and body["cached"] is True and body["version"] == 1 and body["render"]["sha256"]
    assert body["segments"] and "pieces" in body


def test_a_failed_export_render_fails_its_job_with_the_reason(client, project, monkeypatch):
    import app.api.main as main

    def broken(*a, **kw):
        raise RuntimeError("no room left")
    monkeypatch.setattr(main, "_render_now", broken)
    job = client.post("/videos/p1/export", json={"with_proposals": True}).json()["render_job"]
    failed = wait_job(client, job["job_id"])
    assert failed["status"] == "failed" and "no room left" in failed["error_text"] and failed["detail"]["mode"] == "proposals"


def test_the_export_pages_export_is_an_export_job_and_its_answer_is_the_file(client, project):
    started = client.post("/videos/p1/export", json={"purpose": "export"})
    assert started.status_code == 202 and started.json()["render_job"]["kind"] == "export"
    assert wait_job(client, started.json()["render_job"]["job_id"])["status"] == "done"
    out = client.post("/videos/p1/export", json={"purpose": "export"})
    assert out.status_code == 200 and out.json()["render"]["sha256"]
    assert client.get("/videos/p1/receipt").json()["render"]["filename"] == "ad-voltage.mp4"
