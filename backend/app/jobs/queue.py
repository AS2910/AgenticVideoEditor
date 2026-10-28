"""One edit at a time per video (2026-10-25): Up next.

A change asked for while the video is Working waits here, in order, at most
MAX per video: a goal (words for Voltage) or an action (a control pressed,
named by `payload.op`). After a success the next one starts by itself,
planned against the video as it is then; after a failure or a Stop the queue
pauses until the user says Run next or Clear queue.

    add(video_id, kind, label, payload, created_by)   raises QueueFull past MAX
    items(video_id) / get(item_id)                     waiting and running, in order
    edit / remove / reorder / clear
    claim_next(video_id) -> Item | None                the first waiting one, now running
    finish(item_id, status, error)                     done | stopped | failed
    running(video_id) -> Item | None
    recent(video_id) -> list[Item]                     the last ones that ended, for the thread's cards
    left_running() -> list[Item]                       at startup: what a previous server was running

Addendum 3.3 (2026-10-28): the card a queued message shows reads one of
CARD_STATES (the front end's names are in `frontend/src/lib/queueState.ts`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.store.db import Database
from app.timefmt import now_iso

MAX = 3
KINDS = ("goal", "action")
# What a queued action can be: the controls whose change can wait its turn.
OPS = ("add", "add_all", "discard", "revert", "remove_line")
LIVE = ("queued", "running")
# Addendum 3.3: what a card in the thread and in Up next shows, in this order of life.
CARD_STATES = ("queued", "running", "done", "stopped", "failed")
ENDED = ("done", "stopped", "failed")
# Plain sentences for a change that can no longer be touched (edit or remove refused).
STARTED = {"edit": "That one has already started, so it can no longer be edited.",
           "remove": "That one has already started, so it can no longer be removed. Stop it instead."}
ENDED_SENTENCE = {"edit": "That one already ran, so it can no longer be edited.",
                  "remove": "That one already ran, so there is nothing to remove."}


def refusal(item: "Item", what: str) -> str:
    """Why a waiting change cannot be edited or removed any more: it started, or it already ran."""
    return STARTED[what] if item.status == "running" else ENDED_SENTENCE[what]


class QueueFull(ValueError):
    pass


@dataclass(frozen=True)
class Item:
    id: int
    video_id: str
    kind: str
    payload: dict
    label: str
    position: int
    created_by: str | None
    status: str
    error: str | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "video_id": self.video_id, "kind": self.kind, "payload": dict(self.payload),
                "label": self.label, "position": self.position, "created_by": self.created_by,
                "status": self.status, "error": self.error}


def _item(r) -> Item:
    return Item(id=int(r["id"]), video_id=r["video_id"], kind=r["kind"], payload=json.loads(r["payload"] or "{}"),
                label=r["label"], position=int(r["position"]), created_by=r["created_by"], status=r["status"],
                error=r["error"])


class VideoQueue:
    def __init__(self, db: Database) -> None:
        self.db = db

    def items(self, video_id: str) -> list[Item]:
        """What is running and what waits, the running one first, then in order."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_queue WHERE video_id = ? AND status IN ('queued', 'running') "
                             "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, position, id", (video_id,)).fetchall()
        return [_item(r) for r in rows]

    def waiting(self, video_id: str) -> list[Item]:
        return [i for i in self.items(video_id) if i.status == "queued"]

    def get(self, item_id: int) -> Item | None:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM video_queue WHERE id = ?", (item_id,)).fetchone()
        return _item(r) if r else None

    def running(self, video_id: str) -> Item | None:
        return next((i for i in self.items(video_id) if i.status == "running"), None)

    def recent(self, video_id: str, limit: int = 10) -> list[Item]:
        """The last changes that ended (done, stopped, failed), oldest first: a card keeps its last state."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_queue WHERE video_id = ? AND status IN ('done', 'stopped', 'failed') "
                             "ORDER BY id DESC LIMIT ?", (video_id, limit)).fetchall()
        return [_item(r) for r in reversed(rows)]

    def left_running(self) -> list[Item]:
        """Every change marked running, on any video (at startup, a previous server's)."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_queue WHERE status = 'running' ORDER BY id").fetchall()
        return [_item(r) for r in rows]

    def add(self, video_id: str, kind: str, label: str, payload: dict, created_by: str | None) -> Item:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        with self.db.tx() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM video_queue WHERE video_id = ? AND status = 'queued'",
                          (video_id,)).fetchone()["n"]
            if n >= MAX:
                raise QueueFull(f"Up next holds {MAX} changes. Remove one first.")
            last = c.execute("SELECT COALESCE(MAX(position), 0) AS p FROM video_queue WHERE video_id = ?",
                             (video_id,)).fetchone()["p"]
            cur = c.execute("INSERT INTO video_queue (video_id, kind, payload, label, position, created_by, status, created_at, "
                            "workspace_id) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, (SELECT workspace_id FROM videos WHERE id = ?))",
                            (video_id, kind, json.dumps(payload), label[:120], int(last) + 1, created_by, now_iso(), video_id))
            r = c.execute("SELECT * FROM video_queue WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _item(r)

    def edit(self, item_id: int, *, label: str | None = None, payload: dict | None = None) -> Item | None:
        """A waiting change reworded (the words of a goal, a chip's label); a running one is not touched."""
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM video_queue WHERE id = ? AND status = 'queued'", (item_id,)).fetchone()
            if r is None:
                return None
            if label is not None:
                c.execute("UPDATE video_queue SET label = ? WHERE id = ?", (label[:120], item_id))
            if payload is not None:
                c.execute("UPDATE video_queue SET payload = ? WHERE id = ?", (json.dumps(payload), item_id))
            r = c.execute("SELECT * FROM video_queue WHERE id = ?", (item_id,)).fetchone()
        return _item(r)

    def remove(self, item_id: int) -> bool:
        with self.db.tx() as c:
            n = c.execute("UPDATE video_queue SET status = 'removed', finished_at = ? WHERE id = ? AND status = 'queued'",
                          (now_iso(), item_id)).rowcount
        return bool(n)

    def reorder(self, video_id: str, ids: list[int]) -> list[Item]:
        """The waiting changes in the order given; any not named keep their order after them."""
        waiting = self.waiting(video_id)
        known = {i.id for i in waiting}
        order = [i for i in ids if i in known] + [i.id for i in waiting if i.id not in ids]
        with self.db.tx() as c:
            for k, item_id in enumerate(order, start=1):
                c.execute("UPDATE video_queue SET position = ? WHERE id = ?", (k, item_id))
        return self.items(video_id)

    def clear(self, video_id: str) -> int:
        with self.db.tx() as c:
            return c.execute("UPDATE video_queue SET status = 'removed', finished_at = ? WHERE video_id = ? AND status = 'queued'",
                             (now_iso(), video_id)).rowcount

    def claim_next(self, video_id: str) -> Item | None:
        """The first waiting change, marked running (none while one runs)."""
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM video_queue WHERE video_id = ? AND status = 'running'", (video_id,)).fetchone():
                return None
            r = c.execute("SELECT * FROM video_queue WHERE video_id = ? AND status = 'queued' ORDER BY position, id LIMIT 1",
                          (video_id,)).fetchone()
            if r is None:
                return None
            c.execute("UPDATE video_queue SET status = 'running' WHERE id = ?", (r["id"],))
            r = c.execute("SELECT * FROM video_queue WHERE id = ?", (r["id"],)).fetchone()
        return _item(r)

    def finish(self, item_id: int, status: str, error: str | None = None) -> Item | None:
        with self.db.tx() as c:
            c.execute("UPDATE video_queue SET status = ?, error = ?, finished_at = ? WHERE id = ? AND status = 'running'",
                      (status, (error or None) and error[:300], now_iso(), item_id))
            r = c.execute("SELECT * FROM video_queue WHERE id = ?", (item_id,)).fetchone()
        return _item(r) if r else None
