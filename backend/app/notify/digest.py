"""The owner's review digest (C2): comments, approvals and change requests
from review links, batched into one email at most every 10 minutes.

News is queued as it happens (`queue_in`, in the transaction of the change
it reports). `flush(db, sender, now, address_for)` sends one email per owner
whose oldest waiting item is at least `WINDOW_S` old, carrying everything
waiting for them, and marks it all sent; so a burst of comments in a few
minutes is one email, ten minutes after the first. The clock is passed in
(tests drive it); `DigestScheduler` calls `flush` from a thread once a minute
in the running server.

    queue_in(c, owner, kind, project_id=, video_id=, payload=)
    pending(db, owner=None) -> [dict]
    flush(db, sender, now, address_for, link_for=None) -> [Email]
    sentence(item) -> the line an item reads as
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.notify.email import Email, EmailSender
from app.store.db import Database
from app.timefmt import iso, now_iso

log = logging.getLogger("voltage.notify")
WINDOW_S = 600
KINDS = ("comment", "approved", "changes_asked")


def queue_in(c: sqlite3.Connection, owner: str, kind: str, *, project_id: str | None = None,
             video_id: str | None = None, payload: dict | None = None, at: str | None = None) -> None:
    if kind not in KINDS:
        raise ValueError(f"a digest item is one of {', '.join(KINDS)}")
    row = c.execute("SELECT workspace_id FROM videos WHERE id = ?", (video_id or "",)).fetchone()
    c.execute("INSERT INTO notify_queue (workspace_id, owner, project_id, video_id, kind, payload, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (row[0] if row else None, owner, project_id, video_id, kind, json.dumps(payload or {}), at or now_iso()))


def pending(db: Database, owner: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM notify_queue WHERE digested_at IS NULL", []
    if owner is not None:
        sql += " AND owner = ?"
        args.append(owner)
    with db.tx() as c:
        rows = c.execute(sql + " ORDER BY at, id", args).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"] or "{}")} for r in rows]


def _clock(t: float | None) -> str:
    if t is None:
        return ""
    s = int(round(t))
    return f"{s // 60}:{s % 60:02d}"


def sentence(item: dict) -> str:
    """One item as the digest says it, e.g. Priya commented on promo.mp4 at 0:12 (v5): "Bigger logo"."""
    p = item["payload"]
    who = p.get("by") or "A reviewer"
    video = p.get("video") or "a video"
    version = f" v{p['version']}" if p.get("version") else ""
    note = f': "{p["note"]}"' if p.get("note") else "."
    if item["kind"] == "comment":
        place = f"{_clock(p.get('at_s'))}" + (f" (v{p['version']})" if p.get("version") else "")
        return f'{who} commented on {video} at {place}: "{p.get("text", "")}"'
    if item["kind"] == "approved":
        return f"{who} approved {video}{version}{note}"
    return f"{who} asked for changes on {video}{version}{note}"


def _subject(items: list[dict]) -> str:
    if len(items) == 1:
        return sentence(items[0]).split(":")[0].rstrip(".")
    return f"{len(items)} updates from your reviewers"


def flush(db: Database, sender: EmailSender, now: datetime, address_for: Callable[[str], str | None],
          link_for: Callable[[dict], str | None] | None = None) -> list[Email]:
    """Send each owner whose oldest waiting item is WINDOW_S old one digest of everything waiting."""
    cutoff = iso(now - timedelta(seconds=WINDOW_S))
    sent: list[Email] = []
    by_owner: dict[str, list[dict]] = {}
    for item in pending(db):
        if item["at"] <= iso(now):
            by_owner.setdefault(item["owner"], []).append(item)
    for owner, items in by_owner.items():
        if items[0]["at"] > cutoff:
            continue                                   # the first is not 10 minutes old yet: wait for more
        lines = [f"- {sentence(i)}" for i in items]
        link = link_for(items[0]) if link_for else None
        body = "\n".join(["Here is what your reviewers said.", "", *lines, *(["", f"Open the project: {link}"] if link else [])])
        email = Email(to=address_for(owner) or f"owner:{owner}", subject=_subject(items), body=body, kind="digest",
                      owner=owner, workspace_id=items[0]["workspace_id"])
        sender.send(email)
        with db.tx() as c:
            c.executemany("UPDATE notify_queue SET digested_at = ? WHERE id = ?", [(iso(now), i["id"]) for i in items])
        sent.append(email)
    return sent


class DigestScheduler:
    """Runs `tick()` every `every` seconds on a daemon thread until `stop()`."""

    def __init__(self, tick: Callable[[], object], every: float = 60.0) -> None:
        self.tick, self.every = tick, every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="review-digest")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the next minute tries again
                log.exception("review digest")

    def stop(self) -> None:
        self._stop.set()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
