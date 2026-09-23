import threading

from app.jobs.store import JobStore


def test_jobs_get_sequential_ids_and_start_queued():
    store = JobStore()
    first = store.create("preview", "p1")
    second = store.create("preview", "p1")

    assert (first.job_id, second.job_id) == ("j1", "j2")
    assert first.status == "queued"
    assert first.progress == 0.0
    assert first.done is False


def test_update_replaces_fields():
    store = JobStore()
    job = store.create("preview", "p1")

    store.update(job.job_id, status="running", progress=0.5, step="Working")
    fetched = store.get(job.job_id)

    assert (fetched.status, fetched.progress, fetched.step) == ("running", 0.5, "Working")
    assert fetched.project_id == "p1"  # untouched fields survive


def test_a_terminal_job_is_frozen():
    # A worker's last progress callback can land after completion; it must not
    # drag a finished job back to "running".
    store = JobStore()
    job = store.create("preview", "p1")
    store.update(job.job_id, status="succeeded", progress=1.0, result={"ok": True})

    store.update(job.job_id, status="running", progress=0.3, step="Late callback")

    fetched = store.get(job.job_id)
    assert fetched.status == "succeeded"
    assert fetched.progress == 1.0
    assert fetched.result == {"ok": True}


def test_failed_is_also_terminal():
    store = JobStore()
    job = store.create("preview", "p1")
    store.update(job.job_id, status="failed", error="nope")
    store.update(job.job_id, status="running")
    assert store.get(job.job_id).status == "failed"


def test_unknown_job_is_none():
    assert JobStore().get("j99") is None
    assert JobStore().update("j99", status="running") is None


def test_reset_clears_jobs_and_ids():
    store = JobStore()
    store.create("preview", "p1")
    store.reset()
    assert store.get("j1") is None
    assert store.create("preview", "p1").job_id == "j1"


def test_concurrent_creates_do_not_collide():
    store = JobStore()
    ids: list[str] = []
    lock = threading.Lock()

    def make():
        job = store.create("preview", "p1")
        with lock:
            ids.append(job.job_id)

    threads = [threading.Thread(target=make) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(ids)) == 40
