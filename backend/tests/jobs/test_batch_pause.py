"""Run 5 addendum 3, item 5: a batch's pause point is before each video's turn.
Pause: the running video's turn is asked to pause (it holds after its step) and
no other video starts; Resume: the paused one carries on and the rest start in
turn. A pause nobody ends cancels the batch after 30 minutes."""
import threading
import time

from app.jobs.activity import ActivityJobs
from app.jobs.batch import BatchEngine, Child
from app.store.db import Database


def _engine(now):
    db = Database(":memory:")
    meta: dict[str, str] = {}
    activity = ActivityJobs(db)
    seen = {"ran": [], "paused": [], "resumed": []}
    release = threading.Event()

    def run_child(record, child):
        seen["ran"].append(child["video_id"])
        if child["video_id"] == "a":
            assert release.wait(30)
        activity.finish(child["job_id"], detail={"outcome": "current", "spent_usd": 0.0})

    engine = BatchEngine(activity, meta.get, meta.__setitem__, run_child, lambda child, held: None, lambda v: None,
                         concurrency=1, pause_video=seen["paused"].append, resume_video=seen["resumed"].append,
                         clock=lambda: now[0], pause_tick=0.02)
    rec = engine.open_gate("f1", "local", "ask", "g", [Child(video_id=v, filename=v, goal="g", cap_usd=0.5) for v in "abc"])
    return engine, activity, seen, release, rec["batch_id"]


def _until(check, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_pause_holds_every_video_not_started_and_resume_runs_them():
    now = [1000.0]
    engine, activity, seen, release, batch_id = _engine(now)
    engine.go(batch_id)
    assert _until(lambda: seen["ran"] == ["a"])
    engine.pause(batch_id)
    assert seen["paused"] == ["a"]                         # the running video's turn is asked to pause
    assert activity.get(batch_id).step_label == "Paused"
    release.set()                                          # its step finishes
    time.sleep(0.3)
    assert seen["ran"] == ["a"]                            # and no other video starts
    engine.resume(batch_id)
    engine.wait(batch_id, 10)
    assert seen["ran"] == ["a", "b", "c"] and activity.get(batch_id).status == "done"


def test_a_paused_batch_nobody_resumes_is_cancelled_after_30_minutes():
    now = [1000.0]
    engine, activity, seen, release, batch_id = _engine(now)
    engine.go(batch_id)
    assert _until(lambda: seen["ran"] == ["a"])
    engine.pause(batch_id)
    release.set()
    time.sleep(0.2)
    now[0] += 30 * 60 + 1
    engine.wait(batch_id, 10)
    assert seen["ran"] == ["a"] and activity.get(batch_id).status == "cancelled"
