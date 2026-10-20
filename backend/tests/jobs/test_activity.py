"""The one job model (2026-10-20): the state machine, the ETA, the sweeps, the bus."""
import pytest

from app.jobs.activity import ActivityJobs, InvalidTransition
from app.jobs.events import EventBus
from app.store.db import Database


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def jobs(clock):
    return ActivityJobs(Database(":memory:"), clock=clock)


def test_a_job_goes_queued_running_done_and_then_never_changes(jobs):
    job = jobs.create("p1", "voice_line", line_ids=["i1"], detail={"chars": 20})
    assert job.status == "queued" and job.job_id.startswith("J")
    running = jobs.start(job.job_id, "Voicing")
    assert running.status == "running" and running.started_at
    done = jobs.finish(job.job_id, cost_usd=0.02)
    assert done.status == "done" and done.finished_at and done.progress == 1.0
    # A late callback from the worker: frozen.
    assert jobs.update(job.job_id, step_label="Checking fit").step_label == "Done"
    assert jobs.fail(job.job_id, "vendor_failed").status == "done"
    assert jobs.cancel(job.job_id).status == "done"


def test_moves_the_machine_does_not_allow_are_refused(jobs):
    job = jobs.create("p1", "mix")
    with pytest.raises(InvalidTransition):
        jobs._move(job.job_id, "done")                     # queued -> done skips running
    assert jobs.cancel(job.job_id).status == "cancelled"   # queued -> cancelled is fine
    failed = jobs.create("p1", "voice_line")
    jobs.start(failed.job_id)
    out = jobs.fail(failed.job_id, "vendor_failed", "The voice service did not answer.")
    assert out.status == "failed" and out.error_code == "vendor_failed" and out.to_dict()["retryable"]


def test_the_eta_is_never_zero_or_negative(jobs, clock):
    # No history: no estimate at all, rather than a guess.
    first = jobs.create("p1", "voice_line", detail={"chars": 30})
    assert first.eta_s() is None and first.to_dict()["eta_s"] is None
    jobs.start(first.job_id)
    clock.t += 3
    jobs.finish(first.job_id)
    job = jobs.create("p1", "voice_line", detail={"chars": 30})
    assert job.eta_s() >= 1
    jobs.start(job.job_id)
    clock.t += 10_000                                      # far past the estimate
    assert jobs.get(job.job_id).eta_s() == 1
    assert jobs.get(job.job_id).to_dict()["eta_s"] == 1
    tiny = jobs.create("p1", "voice_line", detail={"chars": 1})
    assert tiny.eta_s() >= 1
    assert jobs.finish(job.job_id).to_dict()["eta_s"] is None


def test_the_eta_learns_from_recent_jobs_of_the_same_kind(jobs, clock):
    for chars, secs in ((10, 5.0), (20, 10.0), (40, 20.0)):    # half a second a character
        j = jobs.create("p1", "voice_line", detail={"chars": chars})
        jobs.start(j.job_id)
        clock.t += secs
        jobs.finish(j.job_id)
    assert jobs.estimate("voice_line", 60) == pytest.approx(30.0)
    assert jobs.create("p1", "voice_line", detail={"chars": 60}).eta_s() == 30
    # Another kind has its own history (none yet): no estimate.
    assert jobs.estimate("render_preview") is None


def test_a_running_job_silent_past_its_timeout_fails(jobs, clock):
    job = jobs.create("p1", "voice_line")
    jobs.start(job.job_id)
    clock.t += 30
    assert jobs.sweep() == []
    clock.t += 3600
    swept = jobs.sweep()
    assert [j.job_id for j in swept] == [job.job_id]
    assert jobs.get(job.job_id).status == "failed" and jobs.get(job.job_id).error_code == "timeout"


def test_jobs_a_restarted_server_left_behind_are_failed_as_interrupted(clock):
    db = Database(":memory:")
    before = ActivityJobs(db, clock=clock)
    a = before.create("p1", "voice_line")
    b = before.create("p1", "render_preview")
    before.start(b.job_id)
    done = before.create("p1", "mix")
    before.start(done.job_id)
    before.finish(done.job_id)
    after = ActivityJobs(db, clock=clock)                  # the new process
    left = after.interrupt_leftovers()
    assert {j.job_id for j in left} == {a.job_id, b.job_id}
    assert all(after.get(j).error_code == "interrupted" for j in (a.job_id, b.job_id))
    assert after.get(done.job_id).status == "done"


def test_active_lists_only_queued_and_running_newest_first(jobs):
    a = jobs.create("p1", "voice_line", line_ids=["i1"])
    b = jobs.create("p1", "voice_line", line_ids=["i2"])
    jobs.start(b.job_id)
    c = jobs.create("p1", "mix")
    jobs.cancel(c.job_id)
    jobs.create("p2", "voice_line")
    assert [j.job_id for j in jobs.list("p1", active=True)] == [b.job_id, a.job_id]
    assert [j.job_id for j in jobs.list("p1")] == [c.job_id, b.job_id, a.job_id]
    assert jobs.active_for_line("p1", "i2").job_id == b.job_id


def test_every_change_is_published_on_the_bus(clock):
    bus = EventBus()
    q = bus.subscribe("p1")
    other = bus.subscribe("p2")
    jobs = ActivityJobs(Database(":memory:"), on_change=lambda j: bus.publish(j.video_id, "job.updated", j.to_dict()),
                        clock=clock)
    job = jobs.create("p1", "voice_line")
    jobs.start(job.job_id, "Voicing")
    seen = [q.get_nowait(), q.get_nowait()]
    assert [e for e, _ in seen] == ["job.updated", "job.updated"]
    assert [d["status"] for _, d in seen] == ["queued", "running"]
    assert other.empty()
    bus.unsubscribe("p1", q)
    assert bus.listeners("p1") == 0
