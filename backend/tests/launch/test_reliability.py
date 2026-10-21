"""Launch item 4: reliability. Jobs never stay running; vendor retries are
bounded and carry one idempotency key; health and readiness."""
import httpx
from fastapi.testclient import TestClient

import app.api.main as main
from app.adapters.base import VendorError, idempotency_header, idempotency_scope
from app.jobs.activity import ActivityJobs
from app.jobs.runner import DEFAULT_ATTEMPTS, with_retries
from app.store.db import Database


def test_startup_fails_leftover_jobs_with_a_reason_and_the_sweep_fails_hung_ones():
    clock = [1000.0]
    jobs = ActivityJobs(Database(), clock=lambda: clock[0])
    queued = jobs.create("p1", "voice_line")
    running = jobs.create("p1", "export")
    jobs.start(running.job_id)
    restarted = ActivityJobs(jobs.db, clock=lambda: clock[0])
    restarted.interrupt_leftovers()
    for job_id in (queued.job_id, running.job_id):
        got = restarted.get(job_id)
        assert got.status == "failed" and got.error_text == "The server restarted while this was running. Try again."
    hung = restarted.create("p1", "mix")
    restarted.start(hung.job_id)
    clock[0] += 121
    restarted.sweep()
    assert restarted.get(hung.job_id).status == "failed" and "took too long" in restarted.get(hung.job_id).error_text


def test_a_vendor_call_is_tried_at_most_three_times_with_one_key():
    keys, sleeps = [], []

    def flaky():
        keys.append(idempotency_header("tts", "v1", "Hello")["Idempotency-Key"])
        raise VendorError("503 from the vendor")
    try:
        with_retries(flaky, sleep=sleeps.append)
    except VendorError:
        pass
    assert DEFAULT_ATTEMPTS == 3 and len(keys) == 3 and len(set(keys)) == 1    # two retries, one key
    assert sleeps == sorted(sleeps) and len(sleeps) == 2                          # backoff grows
    with idempotency_scope():
        a = idempotency_header("tts", "v1", "Hello")
    with idempotency_scope():
        b = idempotency_header("tts", "v1", "Hello")
    assert a != b                                                                 # another call, another key


def test_elevenlabs_sends_the_key_and_a_timeout(monkeypatch):
    from app.adapters import elevenlabs
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return httpx.Response(500, text="down", request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    elevenlabs._post("v1", {"text": "Hi"}, "key", 30.0)
    assert seen["headers"]["Idempotency-Key"].startswith("ave-") and seen["timeout"] == 30.0


def test_health_and_ready():
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["ready"] is True
    assert {c["name"] for c in ready.json()["checks"]} >= {"database", "migrations", "storage", "ffmpeg"}


def test_ready_says_503_when_the_database_is_gone(monkeypatch):
    def broken():
        raise RuntimeError("disk I/O error")
    monkeypatch.setattr(main, "_check_database", broken)
    ready = TestClient(main.app).get("/ready")
    assert ready.status_code == 503 and ready.json()["ready"] is False
    assert "disk I/O error" not in ready.text                                    # no internals out
