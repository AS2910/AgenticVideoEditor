"""Job records for work that outlives a request.

Design spec §7: edits run server-side and take on the order of minutes, so the
client is handed a job id and polls. Everything here is in-memory and guarded
by a lock, because jobs are written by worker threads and read by request
threads at the same time.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Literal

JobStatus = Literal["queued", "running", "succeeded", "failed"]

TERMINAL: frozenset[str] = frozenset({"succeeded", "failed"})


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str                     # "preview"
    project_id: str
    status: JobStatus = "queued"
    progress: float = 0.0         # 0.0–1.0
    step: str = "Queued"          # human-readable, shown in the UI
    result: dict | None = None    # payload on success (the candidate)
    error: str | None = None      # user-facing reason on failure
    attempts: int = 0             # vendor calls made, including retries

    @property
    def done(self) -> bool:
        return self.status in TERMINAL


class JobStore:
    """Thread-safe registry of jobs. Jobs are immutable; updates replace them."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._counter = 0

    def create(self, kind: str, project_id: str) -> Job:
        with self._lock:
            self._counter += 1
            job = Job(job_id=f"j{self._counter}", kind=kind, project_id=project_id)
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> Job | None:
        """Apply changes to a job. Terminal jobs are frozen — late progress
        callbacks from a finished worker must not resurrect them."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.done:
                return job
            updated = replace(job, **changes)
            self._jobs[job_id] = updated
            return updated
