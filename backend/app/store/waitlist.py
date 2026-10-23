"""Launch item 8: the waitlist (migration 0035).

    join(db, email, name, use_case) -> bool    True when the address is new
    rows(db, limit) -> [dict]                  newest first, with a status
    invite(db, row_id, by) -> dict | None      marks the row invited (again)
    invited(c, email) -> bool                  inside a transaction: may this address sign up
"""
from __future__ import annotations

from app.store.db import Database
from app.timefmt import now_iso


def _clean(text: str | None, limit: int) -> str | None:
    text = " ".join((text or "").split())[:limit]
    return text or None


def join(db: Database, email: str, name: str | None = None, use_case: str | None = None) -> bool:
    """Add the address (already cleaned, lower case). Asking twice keeps the first row."""
    with db.tx() as c:
        cur = c.execute("INSERT OR IGNORE INTO waitlist (email, name, use_case, created_at) VALUES (?, ?, ?, ?)",
                        (email, _clean(name, 120), _clean(use_case, 500), now_iso()))
        return cur.rowcount == 1


def _row(r) -> dict:
    d = dict(r)
    d["status"] = "invited" if d.get("invited_at") else "waiting"
    return d


def rows(db: Database, limit: int = 500) -> list[dict]:
    with db.tx() as c:
        return [_row(r) for r in c.execute(
            "SELECT id, email, name, use_case, created_at, invited_at, invited_by FROM waitlist ORDER BY id DESC LIMIT ?",
            (limit,))]


def get(db: Database, row_id: int) -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT id, email, name, use_case, created_at, invited_at, invited_by FROM waitlist WHERE id = ?",
                      (row_id,)).fetchone()
    return _row(r) if r else None


def invite(db: Database, row_id: int, by: str) -> dict | None:
    """Mark the row invited by `by`, now (sending again moves the time and the sender)."""
    with db.tx() as c:
        c.execute("UPDATE waitlist SET invited_at = ?, invited_by = ? WHERE id = ?", (now_iso(), by, row_id))
    return get(db, row_id)


def invited(c, email: str) -> bool:
    return c.execute("SELECT 1 FROM waitlist WHERE email = ? AND invited_at IS NOT NULL",
                     (email.lower(),)).fetchone() is not None
