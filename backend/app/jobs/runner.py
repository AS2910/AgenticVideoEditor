"""Runs jobs off the request thread, with bounded retries.

Design spec §8: vendor failures retry with backoff before surfacing a clear
error. `sleep` is injectable so tests exercise the backoff without waiting.
"""
from __future__ import annotations

import logging
import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.adapters.base import VendorError, idempotency_scope
from app.errors import NonRetryableError
from app.jobs.store import Job, JobStore

log = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5


def with_retries(
    work: Callable[[], object],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    on_attempt: Callable[[int], None] | None = None,
    retry_on: tuple[type[BaseException], ...] = (VendorError,),
):
    """Call `work`, retrying transient vendor failures with exponential backoff.
    Every attempt runs in one idempotency scope, so a retried vendor call
    sends the key its first attempt sent (launch item 4)."""
    with idempotency_scope():
        return _attempts(work, attempts, base_delay, sleep, on_attempt, retry_on)


def _attempts(work, attempts, base_delay, sleep, on_attempt, retry_on):
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if on_attempt:
            on_attempt(attempt)
        try:
            return work()
        except retry_on as exc:
            last = exc
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log.warning("attempt %d/%d failed (%s); retrying in %.1fs",
                            attempt, attempts, exc, delay)
                sleep(delay)
    raise last  # type: ignore[misc]


class JobRunner:
    """Owns the worker pool and the job lifecycle."""

    def __init__(
        self,
        jobs: JobStore,
        *,
        max_workers: int = 2,
        attempts: int = DEFAULT_ATTEMPTS,
        base_delay: float = DEFAULT_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.jobs = jobs
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ave-job")
        self._attempts = attempts
        self._base_delay = base_delay
        self._sleep = sleep

    def submit(self, job: Job, work: Callable[[Callable[[float, str], None]], dict]) -> Job:
        """Run `work` in the background.

        `work` receives a `report(progress, step)` callback and returns the
        payload to store on the job.
        """
        # G2: the work carries the request's context (who caused its charges).
        self._pool.submit(contextvars.copy_context().run, self._run, job.job_id, work)
        return job

    def _run(self, job_id: str, work) -> None:
        def report(progress: float, step: str) -> None:
            self.jobs.update(job_id, status="running", progress=progress, step=step)

        def count(attempt: int) -> None:
            self.jobs.update(job_id, attempts=attempt)

        report(0.05, "Starting")
        try:
            result = with_retries(
                lambda: work(report),
                attempts=self._attempts,
                base_delay=self._base_delay,
                sleep=self._sleep,
                on_attempt=count,
            )
        except Exception as exc:  # noqa: BLE001 - a job must never kill the worker
            # Run 5 item 1: one classifier says it. The app's own refusals (widen
            # the selection, raise the ceiling) are shown as written; a vendor,
            # ffmpeg or a bug is "on our end", with the cause logged and reported.
            log.warning("job %s failed: %s", job_id, exc, exc_info=not isinstance(exc, (NonRetryableError, VendorError)))
            from app import failures
            self.jobs.update(job_id, status="failed", step="Failed", error=failures.say(exc, where="job"))
        else:
            self.jobs.update(
                job_id, status="succeeded", progress=1.0, step="Ready", result=result,
            )

    def snapshot(self) -> dict:
        """Where the pool stands, for /health (the chaos pass): how many jobs
        are running or still queued against how many workers. Two hung vendor
        calls fill the default pool, and this is where that shows."""
        running = sum(1 for j in self.jobs.all() if j.status == "running")
        queued = sum(1 for j in self.jobs.all() if j.status == "queued")
        return {"workers": self._pool._max_workers, "running": running, "queued": queued}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
