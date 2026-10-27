"""B3: batch export. Chosen videos times chosen presets, one file each.

A batch export is a parent Activity job (kind `export`, keyed by the
project's id in the video slot, `detail.batch_export`) and one child job per
video x preset (kind `export`, in that video's slot, `detail.parent_id`
naming the parent), the same parent/child linkage F4 uses, without F4's gate
and money: an export renders on this machine and costs nothing, so there is
no plan to approve. Its record (the presets as they were, each file made,
each failure's reason, the pre-flight warnings) lives in meta under
`export:<parent job id>` with an index `exports:<project>`, because a
terminal job never changes and the files are downloaded and shared after the
export ends.

    start(project_id, owner, items, warnings) -> record   children queued, a driver renders two at a time
    get(export_id, project_id=None) / of_project(project_id) / wait(export_id)

The render itself is the caller's (`render_one(record, item) -> file dict`).
A render that raises is tried once more; a second failure fails that child
with the reason and the rest carry on. When every file of a video is made,
`on_video_done(record, video_id)` runs (the caller moves its stage to
Exported); `on_close(record)` runs once at the end.
"""
from __future__ import annotations

import json
import logging
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app import analytics
from app.jobs.activity import ActivityJobs
from app.timefmt import now_iso

log = logging.getLogger(__name__)

KEY = "export:{}"
INDEX = "exports:{}"
# Renders are heavy (the picture is re-encoded at the preset's size): two at a time.
CONCURRENCY = 2
# A failed render is tried once more, then the file is Failed with its reason.
ATTEMPTS = 2


class ExportError(ValueError):
    """Refused, with a sentence for the user."""


def _reason(exc: BaseException) -> str:
    """Run 5 item 1: the classifier's sentence, never ffmpeg's or a vendor's text."""
    from app import failures
    return failures.say(exc, where="export", spent_usd=0.0)       # an export renders what exists: no vendor, no charge


class ExportEngine:
    def __init__(self, activity: ActivityJobs, get_meta: Callable[[str], str | None], set_meta: Callable[[str, str], None],
                 render_one: Callable[[dict, dict], dict], on_video_done: Callable[[dict, str], None] | None = None,
                 on_close: Callable[[dict], None] | None = None, concurrency: int = CONCURRENCY) -> None:
        self.activity = activity
        self.get_meta = get_meta
        self.set_meta = set_meta
        self.render_one = render_one
        self.on_video_done = on_video_done
        self.on_close = on_close
        self.concurrency = concurrency
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    # ── the record ───────────────────────────────────────────────────────
    def _load(self, export_id: str) -> dict | None:
        raw = self.get_meta(KEY.format(export_id))
        return json.loads(raw) if raw else None

    def _save(self, record: dict) -> None:
        self.set_meta(KEY.format(record["export_id"]), json.dumps(record))

    def _change(self, export_id: str, index: int, **fields) -> dict | None:
        with self._lock:
            record = self._load(export_id)
            if record is None:
                return None
            record["items"][index].update(fields)
            self._save(record)
            return record

    def get(self, export_id: str, project_id: str | None = None) -> dict | None:
        """The record with the parent's and every file's job read fresh; None
        when there is no such export (or it is another project's)."""
        record = self._load(export_id)
        if record is None or (project_id is not None and record["project_id"] != project_id):
            return None
        parent = self.activity.get(export_id)
        record["status"] = parent.status if parent else "failed"
        record["step"] = parent.step_label if parent else "Interrupted"
        record["progress"] = parent.progress if parent else 0.0
        for item in record["items"]:
            job = self.activity.get(item["job_id"]) if item.get("job_id") else None
            item["job"] = job.to_dict() if job else None
        return record

    def of_project(self, project_id: str) -> list[str]:
        """The project's export ids, newest first."""
        return list(reversed(json.loads(self.get_meta(INDEX.format(project_id)) or "[]")))

    # ── starting ─────────────────────────────────────────────────────────
    def start(self, project_id: str, owner: str, items: list[dict], warnings: list[dict] | None = None) -> dict:
        """Queue one child per item (each `{video_id, filename, stage, preset}`)
        under one parent, and start the driver."""
        if not items:
            raise ExportError("Pick at least one video and one preset.")
        parent = self.activity.create(project_id, "export", step_label="Queued",
                                      detail={"batch_export": True, "project_id": project_id, "files": len(items)})
        rows = []
        for i, item in enumerate(items):
            job = self.activity.create(item["video_id"], "export", step_label="Queued",
                                       detail={"parent_id": parent.job_id, "project_id": project_id,
                                               "preset": item["preset"]["name"]})
            rows.append({**item, "index": i, "job_id": job.job_id, "attempts": 0, "file": None, "error": None})
        record = {"export_id": parent.job_id, "project_id": project_id, "owner": owner, "created_at": now_iso(),
                  "phase": "running", "warnings": list(warnings or []), "items": rows, "moved": []}
        with self._lock:
            self._save(record)
            ids = json.loads(self.get_meta(INDEX.format(project_id)) or "[]")
            self.set_meta(INDEX.format(project_id), json.dumps(ids + [parent.job_id]))
            self.activity.start(parent.job_id, f"Exporting {len(rows)} {'file' if len(rows) == 1 else 'files'}")
            thread = threading.Thread(target=contextvars.copy_context().run, args=(self._drive, parent.job_id), daemon=True, name=f"export-{parent.job_id}")
            self._threads[parent.job_id] = thread
        thread.start()
        return self.get(parent.job_id)  # type: ignore[return-value]

    def wait(self, export_id: str, timeout: float | None = None) -> None:
        """Tests: until the driver has finished."""
        thread = self._threads.get(export_id)
        if thread is not None:
            thread.join(timeout)

    # ── running ──────────────────────────────────────────────────────────
    def _one(self, export_id: str, index: int) -> None:
        """One file: render it, once more if that fails, then Failed with the reason."""
        record = self._load(export_id)
        if record is None:
            return
        item = record["items"][index]
        job_id = item["job_id"]
        self.activity.start(job_id, f"Rendering {item['preset']['name']}")
        last: BaseException | None = None
        for attempt in range(1, ATTEMPTS + 1):
            self._change(export_id, index, attempts=attempt)
            if attempt > 1:
                self.activity.update(job_id, step_label=f"Trying {item['preset']['name']} again")
            try:
                made = self.render_one(record, {**item, "attempts": attempt})
            except Exception as exc:  # noqa: BLE001 - one file failing never stops the rest
                last = exc
                log.warning("export %s: %s x %s attempt %d failed: %s", export_id, item["video_id"],
                            item["preset"]["name"], attempt, exc)
                continue
            self._change(export_id, index, file=made, error=None)
            self.activity.finish(job_id, step_label="Ready", detail={"file": made.get("name")})
            self._video_done(export_id, item["video_id"])
            self._progress(export_id)
            return
        why = f"The render failed twice. {_reason(last) if last else ''}".strip()
        self._change(export_id, index, error=why)
        self.activity.fail(job_id, "render_failed", why)
        analytics.track("export.file_failed", record.get("owner"), {"export_id": export_id, "video_id": item["video_id"],
                                                                    "preset": item["preset"]["name"]})
        self._progress(export_id)

    def _video_done(self, export_id: str, video_id: str) -> None:
        """Every file of this video made: the caller's hook, once."""
        with self._lock:
            record = self._load(export_id)
            if record is None or video_id in record["moved"]:
                return
            mine = [i for i in record["items"] if i["video_id"] == video_id]
            if not all(i.get("file") for i in mine):
                return
            record["moved"].append(video_id)
            self._save(record)
        if self.on_video_done is not None:
            try:
                self.on_video_done(record, video_id)
            except Exception:  # noqa: BLE001 - bookkeeping never fails the file
                log.exception("export %s: after %s failed", export_id, video_id)

    def _progress(self, export_id: str) -> None:
        record = self._load(export_id)
        if record is None:
            return
        jobs = [self.activity.get(i["job_id"]) for i in record["items"]]
        over = sum(1 for j in jobs if j is not None and j.done)
        ready = sum(1 for i in record["items"] if i.get("file"))
        self.activity.update(export_id, progress=over / max(1, len(jobs)),
                             step_label=f"{ready} of {len(jobs)} files ready")

    def _drive(self, export_id: str) -> None:
        record = self._load(export_id) or {"items": []}
        try:
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=f"export-{export_id}") as pool:
                for future in [pool.submit(contextvars.copy_context().run, self._one, export_id, i) for i in range(len(record["items"]))]:
                    future.result()
        except Exception:  # noqa: BLE001 - the parent always ends
            log.exception("export %s driver failed", export_id)
        finally:
            self._close(export_id)

    def _close(self, export_id: str) -> None:
        with self._lock:
            record = self._load(export_id)
            if record is None:
                return
            for item in record["items"]:
                job = self.activity.get(item["job_id"])
                if job is not None and not job.done:          # a render that never came back
                    self.activity.fail(item["job_id"], "render_failed", "The render ended without a file.")
                    item["error"] = item.get("error") or "The render ended without a file."
            ready = sum(1 for i in record["items"] if i.get("file"))
            failed = len(record["items"]) - ready
            record["phase"] = "finished"
            record["finished_at"] = now_iso()
            record["summary"] = {"ready": ready, "failed": failed}
            self._save(record)
            label = f"{ready} of {len(record['items'])} files ready" + (f", {failed} failed" if failed else "")
            self.activity.finish(export_id, step_label=label, detail={"summary": record["summary"]})
            self._threads.pop(export_id, None)
        if self.on_close is not None:
            try:
                self.on_close(record)
            except Exception:  # noqa: BLE001
                log.exception("export %s: on_close failed", export_id)
