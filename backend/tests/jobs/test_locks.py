"""One edit at a time per video (2026-10-25): the lock itself. Taken
atomically, released only by its holder, handed on, and cleared by the
stuck-job sweep once its lease runs out (a crash stops the renewals)."""
import pytest

from app.jobs.activity import ActivityJobs
from app.jobs.locks import GATE, LEASE, VideoBusy, VideoLocks
from app.store.db import Database


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture()
def setup():
    db = Database()
    clock = Clock()
    heard = []
    locks = VideoLocks(db, clock=clock, on_change=lambda v, lock, outcome: heard.append((v, lock.holder if lock else None, outcome)))
    return db, clock, locks, heard


def test_a_second_holder_is_refused_with_what_holds_it(setup):
    _, _, locks, heard = setup
    locks.take("p1", "J1", "Adding 'Fresh every morning'", started_by="google:ann", started_by_name="Ann", tab="t1")
    with pytest.raises(VideoBusy) as busy:
        locks.take("p1", "J2", "Discarding")
    held = busy.value.lock
    assert (held.holder, held.action, held.started_by_name, held.tab) == ("J1", "Adding 'Fresh every morning'", "Ann", "t1")
    assert locks.get("p1").holder == "J1"
    locks.take("p2", "J2", "Discarding")                     # another video is its own lock
    assert heard == [("p1", "J1", None), ("p2", "J2", None)]


def test_only_the_holder_releases_and_the_release_says_how_it_ended(setup):
    _, _, locks, heard = setup
    locks.take("p1", "J1", "Adding")
    assert not locks.release("p1", "J9")
    assert locks.get("p1") is not None
    assert locks.release("p1", "J1", "failed")
    assert locks.get("p1") is None and heard[-1] == ("p1", None, "failed")


def test_a_request_hands_its_lock_to_the_job_it_started(setup):
    _, _, locks, _ = setup
    locks.take("p1", "req-1", "Adding")
    moved = locks.hand("p1", "req-1", "J7", action="Adding 'Fresh every morning'")
    assert moved.holder == "J7" and moved.action == "Adding 'Fresh every morning'"
    assert locks.hand("p1", "req-1", "J8") is None            # it is not req-1's to hand any more
    assert not locks.release("p1", "req-1") and locks.get("p1").holder == "J7"


def test_a_crash_releases_the_lock_through_lease_expiry(setup):
    db, clock, locks, heard = setup
    jobs = ActivityJobs(db, clock=clock)
    jobs.after_sweep = locks.sweep
    locks.take("p1", "J1", "Adding")
    clock.t += LEASE - 1
    jobs.sweep()
    assert locks.get("p1") is not None                       # inside its lease, nobody touches it
    clock.t += 2                                             # nobody renewed it: the server that held it died
    assert locks.get("p1") is None                           # reads as Ready at once
    jobs.sweep()
    assert locks.all() == [] and heard[-1] == ("p1", None, "expired")
    locks.take("p1", "J2", "Discarding")                     # and the next action takes it


def test_a_live_holder_keeps_renewing_and_a_dead_one_lapses(setup):
    _, clock, locks, _ = setup
    locks.take("p1", "J1", "Adding")
    locks.take("p2", "J2", "Adding")
    clock.t += LEASE - 5
    assert locks.renew_live(lambda lock: lock.holder == "J1") == 1
    clock.t += 10
    assert locks.get("p1") is not None and locks.get("p2") is None


def test_a_waiting_go_survives_a_restart_and_a_running_action_does_not(setup):
    db, clock, _, _ = setup
    first = VideoLocks(db, clock=clock)
    first.take("p1", "J1", "Adding")
    first.take("p2", f"{GATE}j3", "Waiting for your go", lease=3600)
    again = VideoLocks(db, clock=clock)                      # the next server starts
    assert [lock.holder for lock in again.clear_leftovers()] == ["J1"]
    assert again.get("p1") is None and again.get("p2").gate


def test_a_turn_may_take_over_the_go_it_answers(setup):
    _, _, locks, _ = setup
    locks.take("p1", f"{GATE}j3", "Waiting for your go", lease=3600, started_by="local")
    with pytest.raises(VideoBusy):
        locks.take("p1", "req-2", "Discarding")
    took = locks.take("p1", "req-3", "Voltage is planning", over=lambda held: held.gate)
    assert took.holder == "req-3" and not took.gate


def test_the_lock_and_the_job_end_in_one_step():
    db = Database()
    locks = VideoLocks(db)
    jobs = ActivityJobs(db)
    jobs.on_end_in = lambda c, j: locks.release_in(c, j.video_id, j.job_id, "done")
    seen = []
    job = jobs.create("p1", "render_preview", within=lambda c, job_id: locks.take_in(c, "p1", job_id, "Adding"))
    assert locks.get("p1").holder == job.job_id               # taken in the transaction that made the job
    jobs.on_change = lambda j: seen.append((j.status, locks.get("p1")))
    jobs.start(job.job_id)
    jobs.finish(job.job_id)
    assert seen[-1] == ("done", None)                         # whoever hears it done finds the video Ready
