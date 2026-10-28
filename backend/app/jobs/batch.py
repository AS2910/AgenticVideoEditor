"""F4: the batch turn engine. One goal across N videos of a project: one plan,
one gate, then one ordinary turn per video, three at a time.

A batch is a parent Activity job (kind `batch`, keyed by the project's id in
the video slot, like A2's check) and, after Go, one child Activity job per
video (kind `batch`, in that video's own slot, `detail.parent_id` naming the
parent). Its record (what was planned, the gate's totals, who answered what,
what was added) lives in meta under `batch:<parent job id>`, because a
terminal job never changes again and a batch is still read and acted on after
it ends (an answer to a paused video, "Add all that passed").

    open_gate(project_id, owner, source, goal, children, totals, extra) -> record
    go(batch_id, owner)        the one gate's yes: children queued, a driver runs them
    cancel(batch_id)           queued children cancelled; running ones finish (the Stop path)
    pause(batch_id) / resume(batch_id)   addendum 3.5: no video starts while paused; running ones pause after their step
    get(batch_id) / of_project(project_id)

Money: the parent's cap is the sum of its children's caps (each video's turn
cap), shown at the gate. A child reserves its cap inside the parent's before
it starts; `refusal(child, held_usd)` says why it may not (a video, project
or month ceiling it would cross, counting what running children hold) and
the child fails with that sentence while the rest carry on. Each child's
turn charges its own video as any turn does, so Usage shows the batch under
the right videos and project; the parent's figure is the sum of children.

The child's work itself is the caller's (`run_child(record, child)`): it
starts, finishes or fails the child job, setting `detail.outcome`
(updated, proposed, current, waiting) and `detail.spent_usd`. A child whose
turn ends with a question finishes as `waiting`: it pauses alone, its
question is shown on the batch, and the others carry on.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable

from app.jobs.activity import ActivityJobs
from app.jobs.pause import AUTO_STOP_S
from app.timefmt import now_iso

log = logging.getLogger(__name__)

# Decision 3 of the plan: three videos at a time.
CONCURRENCY = 3
KEY = "batch:{}"
INDEX = "batches:{}"
SOURCES = ("ask", "fix", "brief", "language")   # B2: language versions
# How many finished child jobs the time estimate reads.
HISTORY = 20


@dataclass
class Child:
    video_id: str
    filename: str
    goal: str
    cap_usd: float
    stage: str = "draft"
    lines: int | None = None        # lines the goal looks likely to touch; None: Voltage decides
    est_usd: float | None = None    # None when there is nothing measured to estimate from
    job_id: str | None = None
    extra: dict = field(default_factory=dict)   # what the caller's run_child needs (A1: the version it was made with)


class BatchError(ValueError):
    """Refused, with a sentence for the user."""


def _round_up_cent(usd: float) -> float:
    return math.ceil(round(usd * 100, 6)) / 100


class BatchEngine:
    def __init__(self, activity: ActivityJobs, get_meta: Callable[[str], str | None], set_meta: Callable[[str, str], None],
                 run_child: Callable[[dict, dict], None], refusal: Callable[[dict, float], str | None],
                 stop_video: Callable[[str], None], on_close: Callable[[dict], None] | None = None,
                 concurrency: int = CONCURRENCY, pause_video: Callable[[str], None] | None = None,
                 resume_video: Callable[[str], None] | None = None, clock: Callable[[], float] = time.time,
                 pause_tick: float = 0.2) -> None:
        self.activity = activity
        self.get_meta = get_meta
        self.set_meta = set_meta
        self.run_child = run_child
        self.refusal = refusal
        self.stop_video = stop_video
        self.on_close = on_close
        self.concurrency = concurrency
        # Addendum 3.5: Pause and Resume reach each running video's turn through these.
        self.pause_video = pause_video
        self.resume_video = resume_video
        self.clock = clock
        self.pause_tick = pause_tick
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    # ── the record ───────────────────────────────────────────────────────
    def _load(self, batch_id: str) -> dict | None:
        raw = self.get_meta(KEY.format(batch_id))
        return json.loads(raw) if raw else None

    def save(self, record: dict) -> None:
        self.set_meta(KEY.format(record["batch_id"]), json.dumps(record))

    def update(self, batch_id: str, change: Callable[[dict], None]) -> dict | None:
        """Read, change and write the record under the engine's lock."""
        with self._lock:
            record = self._load(batch_id)
            if record is None:
                return None
            change(record)
            self.save(record)
            return record

    def get(self, batch_id: str) -> dict | None:
        """The record with the parent's and every child's job read fresh."""
        record = self._load(batch_id)
        if record is None:
            return None
        parent = self.activity.get(batch_id)
        record["status"] = parent.status if parent else "failed"
        record["step"] = parent.step_label if parent else "Interrupted"
        for child in record["children"]:
            job = self.activity.get(child["job_id"]) if child.get("job_id") else None
            child["job"] = job.to_dict() if job else None
        return record

    def of_project(self, project_id: str) -> list[str]:
        """The project's batch ids, newest first."""
        return list(reversed(json.loads(self.get_meta(INDEX.format(project_id)) or "[]")))

    # ── the gate ─────────────────────────────────────────────────────────
    def open_gate(self, project_id: str, owner: str, source: str, goal: str, children: list[Child],
                  est_s: float | None = None, extra: dict | None = None) -> dict:
        """Plan once and open the one gate: a queued parent job waiting on the
        user, the totals worked out from the children's own estimates. A
        total is left out (None) when any child's part of it is unknown."""
        if source not in SOURCES:
            raise ValueError(f"unknown batch source {source}")
        if not children:
            raise BatchError("Pick at least one video.")
        lines = [c.lines for c in children]
        usd = [c.est_usd for c in children]
        totals = {
            "videos": len(children),
            "lines": sum(lines) if all(n is not None for n in lines) else None,
            "est_usd": _round_up_cent(sum(usd)) if all(u is not None for u in usd) else None,
            "est_s": None if est_s is None else max(1, math.ceil(est_s)),
            "cap_usd": round(sum(c.cap_usd for c in children), 2),
        }
        parent = self.activity.create(project_id, "batch", step_label="Waiting on you",
                                      detail={"project_id": project_id, "source": source, "goal": goal[:300],
                                              "videos": len(children), "cap_usd": totals["cap_usd"]})
        record = {"batch_id": parent.job_id, "project_id": project_id, "owner": owner, "source": source, "goal": goal,
                  "created_at": now_iso(), "phase": "gate", "totals": totals, "extra": dict(extra or {}),
                  "children": [{**asdict(c), "answers": [], "added": None} for c in children]}
        with self._lock:
            self.save(record)
            ids = json.loads(self.get_meta(INDEX.format(project_id)) or "[]")
            self.set_meta(INDEX.format(project_id), json.dumps(ids + [parent.job_id]))
        return self.get(parent.job_id)  # type: ignore[return-value]

    def go(self, batch_id: str) -> dict:
        """The gate's yes: every child queued at once (rows say Queued), and a
        driver runs them three at a time."""
        with self._lock:
            record = self._load(batch_id)
            if record is None:
                raise KeyError(batch_id)
            if record["phase"] != "gate":
                raise BatchError("This batch has already started.")
            parent = self.activity.get(batch_id)
            if parent is None or parent.done:
                raise BatchError("This batch was cancelled.")
            for child in record["children"]:
                job = self.activity.create(child["video_id"], "batch", step_label="Queued",
                                           detail={"parent_id": batch_id, "project_id": record["project_id"],
                                                   "source": record["source"], "cap_usd": child["cap_usd"]})
                child["job_id"] = job.job_id
            record["phase"] = "running"
            record["started_at"] = now_iso()
            self.save(record)
            self.activity.start(batch_id, f"Working on {len(record['children'])} videos")
            thread = threading.Thread(target=contextvars.copy_context().run, args=(self._drive, batch_id), daemon=True, name=f"batch-{batch_id}")
            self._threads[batch_id] = thread
        thread.start()
        return self.get(batch_id)  # type: ignore[return-value]

    def wait(self, batch_id: str, timeout: float | None = None) -> None:
        """Tests: until the driver has finished."""
        thread = self._threads.get(batch_id)
        if thread is not None:
            thread.join(timeout)

    # ── running ──────────────────────────────────────────────────────────
    def _held(self, record: dict) -> float:
        """What the children running now hold of the parent's reservation."""
        held = 0.0
        for child in record["children"]:
            job = self.activity.get(child["job_id"]) if child.get("job_id") else None
            if job is not None and job.status == "running":
                held += float(child["cap_usd"])
        return held

    def _spent(self, record: dict) -> float:
        total = 0.0
        for child in record["children"]:
            job = self.activity.get(child["job_id"]) if child.get("job_id") else None
            if job is not None:
                total += float(job.detail.get("spent_usd") or job.cost_usd or 0.0)
            total += sum(float(a.get("spent_usd") or 0.0) for a in child.get("answers") or [])
        return round(total, 4)

    def _one(self, batch_id: str, index: int) -> None:
        """One child: reserve inside the parent, else stop with the reason; then its work."""
        self._wait_while_paused(batch_id)
        with self._lock:
            record = self._load(batch_id)
            if record is None:
                return
            child = record["children"][index]
            job = self.activity.get(child["job_id"])
            if job is None or job.done:           # cancelled while queued
                return
            if record.get("cancelled"):
                self.activity.cancel(child["job_id"], "Cancelled")
                return
            left = float(record["totals"]["cap_usd"]) - self._spent(record) - self._held(record)
            why = None
            if left + 1e-9 < float(child["cap_usd"]):
                why = (f"The batch has ${max(0.0, left):.2f} left of its ${record['totals']['cap_usd']:.2f} cap, "
                       f"less than this video's ${child['cap_usd']:.2f} turn cap.")
            why = why or self.refusal(child, self._held(record))
            if why:
                self.activity.fail(child["job_id"], "ceiling", why)
                return
            # Reserved: the job is running before the lock is let go, so the next child counts it.
            self.activity.start(child["job_id"], "Voltage is on it")
        try:
            self.run_child(record, child)
        except Exception as exc:  # noqa: BLE001 - one video failing never stops the rest
            log.exception("batch %s: %s failed", batch_id, child["video_id"])
            from app import failures
            self.activity.fail(child["job_id"], "unknown", failures.say(exc, where="batch", video_id=child["video_id"]))
        job = self.activity.get(child["job_id"])
        if job is not None and not job.done:      # a runner that forgot to close its job
            self.activity.fail(child["job_id"], "unknown", "This video's turn ended without a result.")
        self._progress(batch_id)

    def _progress(self, batch_id: str) -> None:
        record = self._load(batch_id)
        if record is None:
            return
        jobs = [self.activity.get(c["job_id"]) for c in record["children"]]
        over = sum(1 for j in jobs if j is not None and j.done)
        self.activity.update(batch_id, progress=over / max(1, len(jobs)),
                             step_label=f"{over} of {len(jobs)} videos finished" if not record.get("cancelled") else "Cancelling")

    def _drive(self, batch_id: str) -> None:
        record = self._load(batch_id) or {"children": []}
        try:
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=f"batch-{batch_id}") as pool:
                for future in [pool.submit(contextvars.copy_context().run, self._one, batch_id, i) for i in range(len(record["children"]))]:
                    future.result()
        except Exception:  # noqa: BLE001 - the parent always ends
            log.exception("batch %s driver failed", batch_id)
        finally:
            self._close(batch_id)

    def _close(self, batch_id: str) -> None:
        """The parent ends saying which videos finished; its cost is the children's."""
        with self._lock:
            record = self._load(batch_id)
            if record is None:
                return
            by: dict[str, list[str]] = {"finished": [], "waiting": [], "failed": [], "cancelled": []}
            for child in record["children"]:
                job = self.activity.get(child["job_id"]) if child.get("job_id") else None
                if job is None or job.status == "failed":
                    by["failed"].append(child["video_id"])
                elif job.status == "cancelled":
                    by["cancelled"].append(child["video_id"])
                elif job.detail.get("outcome") == "waiting":
                    by["waiting"].append(child["video_id"])
                else:
                    by["finished"].append(child["video_id"])
            spent = self._spent(record)
            record["phase"] = "cancelled" if record.get("cancelled") else "finished"
            record["finished_at"] = now_iso()
            record["summary"] = {**by, "spent_usd": spent}
            self.save(record)
            n = len(record["children"])
            label = f"{len(by['finished'])} of {n} videos finished" + (
                f", {len(by['waiting'])} waiting on you" if by["waiting"] else "")
            self.activity.update(batch_id, detail={"summary": record["summary"]})
            if record.get("cancelled"):
                self.activity.cancel(batch_id, "Cancelled. " + label)
            else:
                self.activity.finish(batch_id, step_label=label, cost_usd=spent or None, detail={"summary": record["summary"]})
            self._threads.pop(batch_id, None)
        if self.on_close is not None:
            try:
                self.on_close(record)
            except Exception:  # noqa: BLE001 - the caller's bookkeeping never undoes the batch
                log.exception("batch %s: on_close failed", batch_id)

    # ── cancel ───────────────────────────────────────────────────────────
    def cancel(self, batch_id: str) -> dict:
        """At the gate: the batch is dropped. Running: queued children are
        cancelled and the running ones finish the step they are on (the
        video's Stop), then the parent ends as cancelled."""
        with self._lock:
            record = self._load(batch_id)
            if record is None:
                raise KeyError(batch_id)
            if record["phase"] == "gate":
                record["phase"] = "cancelled"
                record["cancelled"] = True
                self.save(record)
                self.activity.cancel(batch_id, "Cancelled")
                return self.get(batch_id)  # type: ignore[return-value]
            if record["phase"] != "running":
                raise BatchError("This batch has already ended.")
            record["cancelled"] = True
            self.save(record)
            running = []
            for child in record["children"]:
                job = self.activity.get(child["job_id"])
                if job is None or job.done:
                    continue
                if job.status == "queued":
                    self.activity.cancel(child["job_id"], "Cancelled")
                else:
                    running.append(child["video_id"])
            self.activity.update(batch_id, step_label="Cancelling")
        for video_id in running:
            try:
                self.stop_video(video_id)
            except Exception:  # noqa: BLE001 - a stop that fails leaves the turn to finish on its own
                log.exception("batch %s: stopping %s failed", batch_id, video_id)
        return self.get(batch_id)  # type: ignore[return-value]


    # ── pause (addendum 3.5) ─────────────────────────────────────────────
    def pause(self, batch_id: str) -> dict:
        """Pause a running batch: no video's turn starts after this (the pause point
        is before each one), and each running video's turn pauses after its step."""
        def mark(record: dict) -> None:
            if record["phase"] != "running" or record.get("cancelled"):
                raise BatchError("Only a running batch can be paused.")
            record["paused"] = True
            record["paused_at"] = now_iso()
            record["paused_until"] = self.clock() + AUTO_STOP_S
        with self._lock:
            record = self.update(batch_id, mark)
        if record is None:
            raise KeyError(batch_id)
        self.activity.update(batch_id, step_label="Paused")
        for video_id in self._running_videos(record):
            if self.pause_video is not None:
                try:
                    self.pause_video(video_id)
                except Exception:  # noqa: BLE001 - a video that cannot pause finishes on its own
                    log.exception("batch %s: pausing %s failed", batch_id, video_id)
        return self.get(batch_id)  # type: ignore[return-value]

    def resume(self, batch_id: str) -> dict:
        """Resume: the paused videos carry on from their next step and the rest start in turn."""
        def mark(record: dict) -> None:
            if not record.get("paused"):
                raise BatchError("This batch is not paused.")
            record["paused"] = False
            record.pop("paused_until", None)
        with self._lock:
            record = self.update(batch_id, mark)
        if record is None:
            raise KeyError(batch_id)
        for video_id in self._running_videos(record):
            if self.resume_video is not None:
                try:
                    self.resume_video(video_id)
                except Exception:  # noqa: BLE001 - its own auto-stop still ends it
                    log.exception("batch %s: resuming %s failed", batch_id, video_id)
        self._progress(batch_id)
        return self.get(batch_id)  # type: ignore[return-value]

    def _running_videos(self, record: dict) -> list[str]:
        out = []
        for child in record["children"]:
            job = self.activity.get(child["job_id"]) if child.get("job_id") else None
            if job is not None and job.status == "running":
                out.append(child["video_id"])
        return out

    def _wait_while_paused(self, batch_id: str) -> None:
        """The batch's pause point: a video waits here while the batch is paused; a pause
        nobody ends cancels the batch after AUTO_STOP_S, as a paused turn stops itself."""
        while True:
            record = self._load(batch_id)
            if record is None or not record.get("paused") or record.get("cancelled"):
                return
            if self.clock() >= float(record.get("paused_until") or 0):
                log.info("batch %s paused past its deadline; cancelled", batch_id)
                try:
                    self.update(batch_id, lambda r: r.update(paused=False))
                    self.cancel(batch_id)
                except BatchError:
                    pass
                return
            threading.Event().wait(self.pause_tick)


# ── estimates ────────────────────────────────────────────────────────────────

def child_seconds(activity: ActivityJobs) -> float | None:
    """The median time one video's turn took in a batch (or in A1's and A2's
    loops, the same work), from finished jobs; None with no history."""
    with activity.db.tx() as c:
        rows = c.execute("SELECT body FROM jobs WHERE kind IN ('batch', 'brief_update', 'check') AND status = 'done' "
                         "ORDER BY seq DESC LIMIT 200").fetchall()
    took = []
    for r in rows:
        body = json.loads(r["body"])
        detail = body.get("detail") or {}
        if body["kind"] == "batch" and not detail.get("parent_id"):
            continue                      # a parent: the whole batch, not one video
        if body["kind"] == "check" and not detail.get("fix"):
            continue                      # a project check, not a video's turn
        if detail.get("outcome") == "current" and not detail.get("spent_usd"):
            continue                      # skipped for free: no turn ran
        secs = detail.get("seconds")
        if isinstance(secs, (int, float)) and secs > 0:
            took.append(float(secs))
        if len(took) >= HISTORY:
            break
    return statistics.median(took) if took else None


def batch_seconds(per_video: float | None, turns: int, concurrency: int = CONCURRENCY) -> float | None:
    """Rounds of `concurrency` videos, each about one video's median."""
    if per_video is None or turns <= 0:
        return None
    return per_video * math.ceil(turns / concurrency)
