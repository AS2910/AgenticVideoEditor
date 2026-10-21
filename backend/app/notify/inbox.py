"""G4: in-app notifications, per-person settings, spend alerts.

One row per notification for one person (`notifications`): a kind, one
sentence (`title`), an optional detail line (`body`), where it opens
(`link`, a hash route), when it was read. Each person chooses per kind
whether it shows in the app and whether it is emailed
(`notification_settings`; a kind never set uses DEFAULTS). Email goes
through C2's digest (`app/notify/digest.py`): the item is queued in the same
transaction and arrives in the next batched email, never one email per event.

Kinds: job_done (only jobs longer than a threshold), job_failed,
review_comment, approval, changes_requested, spend_alert (50/80/100% of a
ceiling, each once per ceiling and period: `spend_alerts`).
"""
from __future__ import annotations

import sqlite3

from app.notify import digest
from app.store.db import Database
from app.timefmt import now_iso

KINDS = ("job_done", "job_failed", "review_comment", "approval", "changes_requested", "spend_alert")
LABELS = {
    "job_done": "Long work finished",
    "job_failed": "Something failed",
    "review_comment": "Review comments",
    "approval": "Approvals",
    "changes_requested": "Changes asked for",
    "spend_alert": "Spend alerts",
}
HELP = {
    "job_done": "An export, a check, a batch or an import that took more than a minute is done.",
    "job_failed": "Work that stopped with an error, with the reason.",
    "review_comment": "A reviewer commented on a video.",
    "approval": "A reviewer approved a video.",
    "changes_requested": "A reviewer asked for changes.",
    "spend_alert": "A video, a project or the month reached 50%, 80% or 100% of its ceiling.",
}
# (in the app, by email): review news was emailed before G4 (C2's digest), so it stays on.
DEFAULTS = {
    "job_done": (True, False),
    "job_failed": (True, True),
    "review_comment": (True, True),
    "approval": (True, True),
    "changes_requested": (True, True),
    "spend_alert": (True, True),
}
# The digest item each kind is emailed as.
DIGEST_KIND = {"review_comment": "comment", "approval": "approved", "changes_requested": "changes_asked",
               "job_done": "job_done", "job_failed": "job_failed", "spend_alert": "spend_alert"}
THRESHOLDS = (50, 80, 100)
MAX_KEPT = 200


def _settings_in(c: sqlite3.Connection, user: str) -> dict[str, tuple[bool, bool]]:
    out = dict(DEFAULTS)
    for r in c.execute("SELECT kind, in_app, email FROM notification_settings WHERE recipient = ?", (user,)):
        if r["kind"] in out:
            out[r["kind"]] = (bool(r["in_app"]), bool(r["email"]))
    return out


def settings(db: Database, user: str) -> list[dict]:
    with db.tx() as c:
        found = _settings_in(c, user)
    return [{"kind": k, "label": LABELS[k], "help": HELP[k], "in_app": found[k][0], "email": found[k][1]} for k in KINDS]


def set_settings(db: Database, user: str, changes: dict[str, dict]) -> list[dict]:
    unknown = [k for k in changes if k not in KINDS]
    if unknown:
        raise ValueError(f"Unknown kind: {', '.join(unknown)}.")
    with db.tx() as c:
        now = _settings_in(c, user)
        for kind, change in changes.items():
            in_app = bool(change.get("in_app", now[kind][0]))
            email = bool(change.get("email", now[kind][1]))
            c.execute("INSERT INTO notification_settings (recipient, kind, in_app, email) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT (recipient, kind) DO UPDATE SET in_app = excluded.in_app, email = excluded.email",
                      (user, kind, int(in_app), int(email)))
    return settings(db, user)


def add_in(c: sqlite3.Connection, user: str, kind: str, title: str, *, body: str = "", link: str | None = None,
           workspace_id: str | None = None, video_id: str | None = None, project_id: str | None = None,
           digest_payload: dict | None = None) -> int | None:
    """One notification for `user`, as their settings say: a row when in-app
    is on, a digest item when email is on. Returns the row id, or None."""
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind}")
    in_app, email = _settings_in(c, user)[kind]
    made = None
    if in_app:
        cur = c.execute("INSERT INTO notifications (workspace_id, recipient, kind, title, body, link, video_id, project_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (workspace_id, user, kind, title[:300], body[:500], link, video_id, project_id, now_iso()))
        made = int(cur.lastrowid)
        # Keep the newest MAX_KEPT per person; older ones go.
        c.execute("DELETE FROM notifications WHERE recipient = ? AND id NOT IN "
                  "(SELECT id FROM notifications WHERE recipient = ? ORDER BY id DESC LIMIT ?)", (user, user, MAX_KEPT))
    if email:
        digest.queue_in(c, user, DIGEST_KIND[kind], project_id=project_id, video_id=video_id,
                        payload=digest_payload or {"text": title + (f" {body}" if body else "")})
    return made


def add(db: Database, user: str, kind: str, title: str, **kw) -> int | None:
    with db.tx() as c:
        return add_in(c, user, kind, title, **kw)


def _row(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"], "link": r["link"],
            "video_id": r["video_id"], "project_id": r["project_id"], "created_at": r["created_at"], "read": r["read_at"] is not None}


def list_for(db: Database, user: str, limit: int = 30) -> list[dict]:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM notifications WHERE recipient = ? ORDER BY id DESC LIMIT ?", (user, max(1, min(limit, 100)))).fetchall()
    return [_row(r) for r in rows]


def unread(db: Database, user: str) -> int:
    with db.tx() as c:
        return int(c.execute("SELECT COUNT(*) FROM notifications WHERE recipient = ? AND read_at IS NULL", (user,)).fetchone()[0])


def mark_read(db: Database, user: str, ids: list[int] | None = None) -> int:
    """Mark these (or, with None, all of this person's) read. Returns how many changed."""
    with db.tx() as c:
        if ids is None:
            return c.execute("UPDATE notifications SET read_at = ? WHERE recipient = ? AND read_at IS NULL", (now_iso(), user)).rowcount
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        return c.execute(f"UPDATE notifications SET read_at = ? WHERE recipient = ? AND read_at IS NULL AND id IN ({marks})",
                         (now_iso(), user, *ids)).rowcount


def crossed(spent: float, ceiling: float | None) -> int | None:
    """The highest threshold reached (50, 80 or 100), or None."""
    if not ceiling or ceiling <= 0:
        return None
    share = spent / ceiling * 100
    hit = [t for t in THRESHOLDS if share + 1e-9 >= t]
    return hit[-1] if hit else None


def spend_alert_once(c: sqlite3.Connection, owner: str, scope: str, scope_id: str, period: str, threshold: int) -> bool:
    """True the first time this threshold is reached for this scope and period
    (lower thresholds reached on the way are marked too, so a jump straight
    to 100% says 100% once, not three times)."""
    new = c.execute("INSERT OR IGNORE INTO spend_alerts (owner, scope, scope_id, period, threshold, at) VALUES (?, ?, ?, ?, ?, ?)",
                    (owner, scope, scope_id, period, threshold, now_iso())).rowcount > 0
    for lower in (t for t in THRESHOLDS if t < threshold):
        c.execute("INSERT OR IGNORE INTO spend_alerts (owner, scope, scope_id, period, threshold, at) VALUES (?, ?, ?, ?, ?, ?)",
                  (owner, scope, scope_id, period, lower, now_iso()))
    return new
