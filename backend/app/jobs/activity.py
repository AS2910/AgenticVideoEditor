"""The user-facing job record (2026-10-20, one processing model).

Every piece of work the user waits on (a line voiced, a voice made or cloned,
a mix change, a render) is one Job here, persisted, so a reload or a restart
can say exactly what is running and what happened. The in-memory JobStore
still runs turns; this is what the editor reads.

The state machine is strict: queued -> running -> done | failed | cancelled,
and queued -> cancelled | failed. A terminal job never changes again, so a
late progress callback from a finished worker cannot resurrect it.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Iterable

from app.store.db import Database
from app.store.workspaces import stamp_last
from app.timefmt import now_iso

# brief_update (A1): one video brought up to date with its project's brief, its turn included.
# check (A2): a project check, keyed by the project's id in the video slot (it belongs to no one video);
# also each video's turn in a "Fix in all" from the check.
# batch (F4): a batch turn's parent, keyed by the project's id like a check, and each video's child
# (in that video's slot, `detail.parent_id` naming the parent).
# export (B3) also names a batch export: its parent keyed by the project's id (`detail.batch_export`)
# and one child per video x preset in that video's slot (`detail.parent_id`).
# learn (D2): the learned-style pass, keyed by the project's id like a check.
# import (G1): a video imported from a link, keyed by the owner's own store id (`user-<owner>`).
# separate (run 5 item 8): the voice apart from the music or noise under it, started by an upload that has a bed.
KINDS = ("voice_line", "design_voice", "clone", "mix", "render_preview", "export", "brief_update", "check", "batch",
         "learn", "import", "data_export", "separate")
TERMINAL = frozenset({"done", "failed", "cancelled"})
ACTIVE = frozenset({"queued", "running"})
ALLOWED = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"done", "failed", "cancelled"},
}

# No starting guesses: a kind with no finished job yet has no estimate, and
# nothing shows a time for it (no number that was not measured).
# A running job silent for longer than this has hung: it is failed, never left running.
TIMEOUT_SECONDS = {"voice_line": 300.0, "design_voice": 300.0, "clone": 300.0, "mix": 120.0,
                   "render_preview": 900.0, "export": 1800.0, "brief_update": 1800.0, "check": 1800.0,
                   # A parent waits on rounds of child turns (each up to 30 min); it is touched as each child ends.
                   "batch": 3600.0, "learn": 600.0, "import": 1800.0,
                   "data_export": 1800.0,
                   # Run 5 item 8: the voice apart from the music, after an upload (Demucs on CPU, about half real time).
                   "separate": 1800.0}
HISTORY = 20

ERROR_TEXT = {
    "timeout": "This took too long and was stopped. Try again.",
    "interrupted": "The server restarted while this was running. Try again.",
}


class InvalidTransition(ValueError):
    """A non-terminal job asked to move where the state machine does not go."""


@dataclass(frozen=True)
class Job:
    job_id: str
    video_id: str
    kind: str
    status: str = "queued"
    turn_id: str | None = None
    step_label: str = "Queued"
    progress: float = 0.0
    line_ids: tuple[str, ...] = ()
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_text: str | None = None
    cost_usd: float | None = None
    detail: dict = field(default_factory=dict)
    estimate_s: float | None = None  # whole-job estimate at creation; None until the kind has history
    started_epoch: float | None = None
    params: dict | None = None       # what a retry needs; never sent to the client

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    def eta_s(self, now: float | None = None) -> int | None:
        """Whole seconds left, never 0 or negative; None once it is over."""
        if self.done or self.estimate_s is None:
            return None
        left = self.estimate_s
        if self.status == "running" and self.started_epoch is not None:
            left = self.estimate_s - ((now or time.time()) - self.started_epoch)
        return max(1, math.ceil(left))

    def to_dict(self, now: float | None = None) -> dict:
        return {
            "job_id": self.job_id, "video_id": self.video_id, "turn_id": self.turn_id, "kind": self.kind,
            "status": self.status, "step_label": self.step_label, "progress": round(self.progress, 3),
            "line_ids": list(self.line_ids), "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "eta_s": self.eta_s(now), "error_code": self.error_code,
            "error_text": self.error_text, "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "retryable": self.status == "failed" and self.kind in ("voice_line", "render_preview", "export"),
            "detail": dict(self.detail),
        }


def _load(body: str) -> Job:
    raw = json.loads(body)
    raw["line_ids"] = tuple(raw.get("line_ids") or ())
    return Job(**raw)


def _dump(job: Job) -> str:
    return json.dumps({**asdict(job), "line_ids": list(job.line_ids)})


class ActivityJobs:
    """Persisted jobs, with the state machine, the ETA and the sweeps.
    `on_change(job)` hears every change (the event bus)."""

    def __init__(self, db: Database, on_change: Callable[[Job], None] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.db = db
        self.on_change = on_change
        self.clock = clock
        # 2026-10-25: what else the stuck-job sweep clears (the video locks whose lease ran out),
        # and what ends with a job in the same transaction (its video's lock); the latter returns
        # what to tell once the transaction is over.
        self.after_sweep: Callable[[], object] | None = None
        self.on_end_in: Callable[[object, Job], Callable[[], None] | None] | None = None

    # ── reading ──────────────────────────────────────────────────────────
    def get(self, job_id: str) -> Job | None:
        with self.db.tx() as c:
            row = c.execute("SELECT body FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _load(row["body"]) if row else None

    def list(self, video_id: str, *, active: bool = False, limit: int = 50) -> list[Job]:
        """Newest first."""
        self.sweep()
        sql = "SELECT body FROM jobs WHERE project_id = ?"
        if active:
            sql += " AND status IN ('queued', 'running')"
        with self.db.tx() as c:
            rows = c.execute(sql + " ORDER BY seq DESC LIMIT ?", (video_id, limit)).fetchall()
        return [_load(r["body"]) for r in rows]

    def of_turn(self, video_id: str, turn_id: str) -> list[Job]:
        """Oldest first: the turn's own steps, in the order they began."""
        with self.db.tx() as c:
            rows = c.execute("SELECT body FROM jobs WHERE project_id = ? AND turn_id = ? ORDER BY seq",
                             (video_id, turn_id)).fetchall()
        return [_load(r["body"]) for r in rows]

    def active_for_line(self, video_id: str, line_id: str, kind: str = "voice_line") -> Job | None:
        for job in self.list(video_id, active=True, limit=200):
            if job.kind == kind and line_id in job.line_ids:
                return job
        return None

    # ── the ETA ──────────────────────────────────────────────────────────
    def estimate(self, kind: str, chars: int | None = None) -> float | None:
        """The median of recent finished jobs of the same kind (per character
        for a voice line, times this one's characters); None while there is no
        history. Always at least a second."""
        with self.db.tx() as c:
            rows = c.execute("SELECT body FROM jobs WHERE kind = ? AND status = 'done' ORDER BY seq DESC LIMIT ?",
                             (kind, HISTORY)).fetchall()
        took: list[tuple[float, int | None]] = []
        for r in rows:
            j = _load(r["body"])
            if kind == "export" and (j.detail.get("batch_export") or j.detail.get("parent_id")):
                continue                  # B3: a batch export's file or its whole run, not one export of the video
            secs = j.detail.get("seconds")
            if isinstance(secs, (int, float)) and secs > 0:
                took.append((float(secs), j.detail.get("chars")))
        if kind == "voice_line" and chars:
            rates = [s / n for s, n in took if n]
            if rates:
                return max(1.0, statistics.median(rates) * chars)
        if took:
            return max(1.0, statistics.median(s for s, _ in took))
        return None

    # ── writing ──────────────────────────────────────────────────────────
    def create(self, video_id: str, kind: str, *, turn_id: str | None = None, line_ids: Iterable[str] = (),
               step_label: str = "Queued", detail: dict | None = None, params: dict | None = None,
               within: Callable | None = None) -> Job:
        """`within(c, job_id)` runs inside the transaction that makes the job
        (2026-10-25: the video's lock passes to the job in that same step)."""
        if kind not in KINDS:
            raise ValueError(f"unknown job kind {kind}")
        detail = dict(detail or {})
        # Launch item 1: who started it (a member acting in someone's workspace), so its notice reaches them.
        if "started_by" not in detail:
            from app.usage import current_actor
            if current_actor.get():
                detail["started_by"] = current_actor.get()
        est = self.estimate(kind, detail.get("chars"))
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO jobs (job_id, project_id, turn_id, kind, status, touched, body) "
                            "VALUES ('', ?, ?, ?, 'queued', ?, '{}')", (video_id, turn_id, kind, self.clock()))
            # A project-level job (A2's check) has the project's id here: its workspace is the project's.
            stamp_last(c, "jobs", video_id, video_id)
            job = Job(job_id=f"J{cur.lastrowid}", video_id=video_id, kind=kind, turn_id=turn_id, step_label=step_label,
                      line_ids=tuple(line_ids), created_at=now_iso(), detail=detail, estimate_s=est, params=params)
            c.execute("UPDATE jobs SET job_id = ?, body = ? WHERE seq = ?", (job.job_id, _dump(job), cur.lastrowid))
            if within is not None:
                within(c, job.job_id)
        self._tell(job)
        return job

    def _move(self, job_id: str, status: str | None = None, **changes) -> Job | None:
        """Apply changes under the state machine. A terminal job is frozen
        (returned as it is); a move the machine does not allow raises."""
        with self.db.tx() as c:
            row = c.execute("SELECT body FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            job = _load(row["body"])
            if job.done:
                return job
            if status is not None and status != job.status:
                if status not in ALLOWED.get(job.status, ()):
                    raise InvalidTransition(f"{job.job_id}: {job.status} -> {status}")
                changes["status"] = status
                if status == "running":
                    changes.setdefault("started_at", now_iso())
                    changes["started_epoch"] = self.clock()
                if status in TERMINAL:
                    changes["finished_at"] = now_iso()
                    if job.started_epoch is not None:
                        changes["detail"] = {**changes.get("detail", job.detail),
                                             "seconds": round(self.clock() - job.started_epoch, 2)}
            new = replace(job, **changes)
            c.execute("UPDATE jobs SET status = ?, touched = ?, body = ? WHERE job_id = ?",
                      (new.status, self.clock(), _dump(new), job_id))
            after = self.on_end_in(c, new) if new.done and self.on_end_in is not None else None
        self._tell(new)
        if after is not None:
            after()
        return new

    def start(self, job_id: str, step_label: str | None = None) -> Job | None:
        return self._move(job_id, "running", **({"step_label": step_label} if step_label else {}))

    def update(self, job_id: str, *, step_label: str | None = None, progress: float | None = None,
               detail: dict | None = None, line_ids: Iterable[str] | None = None, params: dict | None = None) -> Job | None:
        changes: dict = {}
        if params is not None:
            changes["params"] = params
        if step_label is not None:
            changes["step_label"] = step_label
        if progress is not None:
            changes["progress"] = min(1.0, max(0.0, float(progress)))
        if line_ids is not None:
            changes["line_ids"] = tuple(line_ids)
        if detail:
            current = self.get(job_id)
            changes["detail"] = {**(current.detail if current else {}), **detail}
        return self._move(job_id, None, **changes)

    def finish(self, job_id: str, *, step_label: str = "Done", cost_usd: float | None = None,
               detail: dict | None = None) -> Job | None:
        current = self.get(job_id)
        if current is None or current.done:
            return current
        return self._move(job_id, "done", step_label=step_label, progress=1.0, cost_usd=cost_usd,
                          detail={**current.detail, **(detail or {})})

    def fail(self, job_id: str, code: str, text: str | None = None, *, cost_usd: float | None = None) -> Job | None:
        return self._move(job_id, "failed", step_label="Failed", error_code=code,
                          error_text=(text or ERROR_TEXT.get(code) or "Something went wrong.")[:300], cost_usd=cost_usd)

    def cancel(self, job_id: str, why: str = "Cancelled") -> Job | None:
        return self._move(job_id, "cancelled", step_label=why)

    def instant(self, video_id: str, kind: str, label: str, **kw) -> Job:
        """Work that is over as soon as it starts (a mix change): one record, done."""
        job = self.create(video_id, kind, step_label=label, **kw)
        self.start(job.job_id)
        return self.finish(job.job_id, step_label=label)  # type: ignore[return-value]

    # ── the sweeps: nothing stays running forever ───────────────────────
    def sweep(self) -> list[Job]:
        """Fail every running job silent past its kind's timeout."""
        now = self.clock()
        with self.db.tx() as c:
            rows = c.execute("SELECT job_id, kind, touched FROM jobs WHERE status = 'running'").fetchall()
        late = [r["job_id"] for r in rows if now - r["touched"] > TIMEOUT_SECONDS.get(r["kind"], 600.0)]
        failed = [j for j in (self.fail(job_id, "timeout") for job_id in late) if j is not None]
        if self.after_sweep is not None:
            self.after_sweep()
        return failed

    def interrupt_leftovers(self) -> list[Job]:
        """At startup: whatever a previous server left queued or running can
        never finish now; it is failed as interrupted."""
        with self.db.tx() as c:
            rows = c.execute("SELECT job_id FROM jobs WHERE status IN ('queued', 'running')").fetchall()
        return [j for j in (self.fail(r["job_id"], "interrupted") for r in rows) if j is not None]

    def _tell(self, job: Job) -> None:
        if self.on_change is not None:
            try:
                self.on_change(job)
            except Exception:  # noqa: BLE001 - a listener never breaks the work
                pass
