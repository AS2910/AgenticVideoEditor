"""The email interface (C2, kept general for G4).

Everything that emails goes through an `EmailSender`. The only provider here
is the fake one, `OutboxEmail`: it sends nothing and writes each email to the
`notify_outbox` table, so tests and the owner can read what would have gone
out. A real provider (Postmark, SES, Resend...) implements `send` and is
chosen by `AVE_EMAIL_PROVIDER` (see SETUP_NEEDED.md); until one exists any
other name falls back to the outbox with a warning.

    Email(to, subject, body, kind, owner=None, workspace_id=None)
    sender_for(name, db)          -> EmailSender
    outbox(db, kind=None, to=None) -> [dict]  newest last
    remember_address(db, owner, email) / address_for(db, owner, fallback=None)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app import analytics
from app.store.db import Database
from app.timefmt import now_iso

log = logging.getLogger("voltage.notify")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str
    kind: str                      # digest | version_ready | review_invite (G4 adds its own)
    owner: str | None = None
    workspace_id: str | None = None


class EmailSender(Protocol):
    name: str

    def send(self, email: Email) -> None: ...


# G7: what each email kind is called in analytics.
SENT_EVENTS = {"digest": "notify.digest_sent", "version_ready": "notify.version_ready_sent",
               "review_invite": "notify.review_invite_sent"}


class OutboxEmail:
    """The fake provider: no email leaves the machine; each one is a row in `notify_outbox`."""

    name = "outbox"

    def __init__(self, db: Database) -> None:
        self.db = db

    def send(self, email: Email) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO notify_outbox (workspace_id, owner, to_addr, kind, subject, body, provider, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (email.workspace_id, email.owner, email.to, email.kind, email.subject, email.body, self.name, now_iso()))
            sent = SENT_EVENTS.get(email.kind)
            if sent and email.owner:
                analytics.safe_in(c, sent, email.owner, {"kind": email.kind}, workspace_id=email.workspace_id)
        log.info("email (outbox) kind=%s to=%s subject=%r", email.kind, email.to, email.subject)


def sender_for(name: str | None, db: Database) -> EmailSender:
    if (name or "outbox") not in ("outbox", "fake"):
        log.warning("email provider %r is not set up here; writing emails to the outbox instead", name)
    return OutboxEmail(db)


def valid_address(address: str | None) -> bool:
    return bool(address) and bool(EMAIL_RE.match(address or "")) and len(address or "") <= 254


def outbox(db: Database, kind: str | None = None, to: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM notify_outbox WHERE 1 = 1", []
    for column, value in (("kind", kind), ("to_addr", to)):
        if value is not None:
            sql += f" AND {column} = ?"
            args.append(value)
    with db.tx() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY id", args).fetchall()]


def remember_address(db: Database, owner: str, address: str | None) -> None:
    """The owner's email, as their sign-in gave it (where their digest goes)."""
    if not valid_address(address):
        return
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"notify_email:{owner}", address))


def address_for(db: Database, owner: str, fallback: str | None = None) -> str | None:
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (f"notify_email:{owner}",)).fetchone()
    return row[0] if row else (fallback if valid_address(fallback) else None)
