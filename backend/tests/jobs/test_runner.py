import time

import pytest

from app.adapters.base import VendorError
from app.jobs.runner import JobRunner, with_retries
from app.jobs.store import JobStore


def await_job(store, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get(job_id)
        if job.done:
            return job
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} never finished: {store.get(job_id)}")


# ── with_retries ─────────────────────────────────────────────────────────────

def test_a_succeeding_call_runs_once():
    calls = []
    result = with_retries(lambda: calls.append(1) or "ok", sleep=lambda _: None)
    assert result == "ok"
    assert len(calls) == 1


def test_a_transient_failure_is_retried_then_succeeds():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise VendorError("temporarily unavailable")
        return "recovered"

    assert with_retries(flaky, sleep=lambda _: None) == "recovered"
    assert len(attempts) == 3


def test_backoff_delays_grow_exponentially():
    slept: list[float] = []

    def always_fails():
        raise VendorError("down")

    with pytest.raises(VendorError):
        with_retries(always_fails, attempts=4, base_delay=0.5, sleep=slept.append)

    # One sleep fewer than attempts — no wait after the final failure.
    assert slept == [0.5, 1.0, 2.0]


def test_the_last_error_is_raised_after_exhausting_attempts():
    def always_fails():
        raise VendorError("rate limited")

    with pytest.raises(VendorError, match="rate limited"):
        with_retries(always_fails, attempts=2, sleep=lambda _: None)


def test_non_vendor_errors_are_not_retried():
    attempts = []

    def bug():
        attempts.append(1)
        raise ValueError("a real bug")

    with pytest.raises(ValueError):
        with_retries(bug, sleep=lambda _: None)
    assert len(attempts) == 1  # surfaced immediately, not retried


# ── JobRunner ────────────────────────────────────────────────────────────────

@pytest.fixture()
def runner():
    store = JobStore()
    made = JobRunner(store, attempts=3, sleep=lambda _: None)
    yield store, made
    made.shutdown()


def test_a_successful_job_reports_progress_then_a_result(runner):
    store, job_runner = runner
    job = store.create("preview", "p1")

    def work(report):
        report(0.5, "Halfway")
        return {"candidate_id": "c1"}

    job_runner.submit(job, work)
    finished = await_job(store, job.job_id)

    assert finished.status == "succeeded"
    assert finished.progress == 1.0
    assert finished.step == "Ready"
    assert finished.result == {"candidate_id": "c1"}
    assert finished.error is None


def test_a_failing_job_surfaces_an_error_not_a_crash(runner):
    store, job_runner = runner
    job = store.create("preview", "p1")

    def work(report):
        raise VendorError("vendor exploded")

    job_runner.submit(job, work)
    finished = await_job(store, job.job_id)

    assert finished.status == "failed"
    assert "Try again" in finished.error
    assert finished.result is None
    # Retried the full allowance before giving up.
    assert finished.attempts == 3


def test_a_job_that_recovers_on_retry_still_succeeds(runner):
    store, job_runner = runner
    job = store.create("preview", "p1")
    tries = []

    def work(report):
        tries.append(1)
        if len(tries) < 2:
            raise VendorError("flaky")
        return {"ok": True}

    job_runner.submit(job, work)
    finished = await_job(store, job.job_id)

    assert finished.status == "succeeded"
    assert finished.attempts == 2


def test_an_unexpected_bug_fails_the_job_without_killing_the_worker(runner):
    store, job_runner = runner
    first = store.create("preview", "p1")
    job_runner.submit(first, lambda report: (_ for _ in ()).throw(ValueError("bug")))
    assert await_job(store, first.job_id).status == "failed"

    # The pool is still usable afterwards.
    second = store.create("preview", "p1")
    job_runner.submit(second, lambda report: {"ok": True})
    assert await_job(store, second.job_id).status == "succeeded"


# ── non-retryable failures (Phase 4a) ────────────────────────────────────────

def test_a_non_retryable_failure_runs_once_and_shows_its_own_message(runner):
    from app.errors import NonRetryableError
    store, job_runner = runner
    job = store.create("preview", "p1")
    tries = []

    def work(report):
        tries.append(1)
        raise NonRetryableError("Widen the selection.")

    job_runner.submit(job, work)
    finished = await_job(store, job.job_id)

    assert finished.status == "failed"
    assert finished.error == "Widen the selection."
    assert finished.attempts == 1
    assert len(tries) == 1


def test_the_phase_4a_refusals_are_all_non_retryable():
    from app.errors import NonRetryableError
    from app.budget import BudgetExceeded
    from app.media.ffmpeg import SpanMismatch
    from app.adapters.elevenlabs import VoiceConfigError
    for kind in (BudgetExceeded, SpanMismatch, VoiceConfigError):
        assert issubclass(kind, NonRetryableError)
        assert not issubclass(kind, VendorError)
