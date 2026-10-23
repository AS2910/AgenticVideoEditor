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
    flush(db, sender, now, address_for, link_for=None, public_url=None) -> [Email]
        (item 9: the bodies come from templates.py; one failed job or spend alert reads as its own email)
    sentence(item) -> the line an item reads as
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from app.notify import templates
from app.notify.email import Email, EmailSender
from app.store.db import Database
from app.timefmt import iso, now_iso

log = logging.getLogger("voltage.notify")
WINDOW_S = 600
REVIEW_KINDS = ("comment", "approved", "changes_asked")
# G4: the other notifications a person chose to have emailed ride the same digest.
KINDS = REVIEW_KINDS + ("job_done", "job_failed", "spend_alert", "abuse_report")


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
    if item["kind"] not in REVIEW_KINDS:
        return str(p.get("text") or "")
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
    if all(i["kind"] in REVIEW_KINDS for i in items):
        return f"{len(items)} updates from your reviewers"
    return f"{len(items)} updates from Voltage"


def _origin(link: str | None) -> str | None:
    if not link:
        return None
    u = urlsplit(link)
    return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else None


def _email(owner: str, to: str, items: list[dict], link: str | None, public_url: str | None) -> Email:
    """Item 9: one item that carries its own email (a failed job, a spend alert) reads as that
    email; anything else is the digest. Either way it is sent as kind `digest`."""
    base = public_url or _origin(link)
    wid = items[0]["workspace_id"]
    own = items[0]["payload"].get("email") if len(items) == 1 else None
    if isinstance(own, dict) and own.get("template") in ("job_failed", "spend_alert"):
        data = {k: v for k, v in own.items() if k != "template"}
        data["link"] = data.get("link") or link
        return templates.email(own["template"], to, public_url=base, owner=owner, workspace_id=wid, sent_as="digest", **data)
    reviewers = all(i["kind"] in REVIEW_KINDS for i in items)
    return templates.email("digest", to, public_url=base, owner=owner, workspace_id=wid, sent_as="digest",
                           subject=_subject(items), items=[sentence(i) for i in items], link=link, reviewers=reviewers)


def flush(db: Database, sender: EmailSender, now: datetime, address_for: Callable[[str], str | None],
          link_for: Callable[[dict], str | None] | None = None, public_url: str | None = None) -> list[Email]:
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
        link = link_for(items[0]) if link_for else None
        email = _email(owner, address_for(owner) or f"owner:{owner}", items, link, public_url)
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
            except Exception:
                log.exception("review digest")

    def stop(self) -> None:
        self._stop.set()


def utcnow() -> datetime:
    return datetime.now(UTC)
