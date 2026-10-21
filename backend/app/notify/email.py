"""The email interface (C2, kept general for G4).

Everything that emails goes through an `EmailSender`. The default is the
fake one, `OutboxEmail`: it sends nothing and writes each email to the
`notify_outbox` table, so tests and the owner can read what would have gone
out. Item 7: `ResendEmail` sends through Resend's API, chosen when
`AVE_EMAIL_PROVIDER=resend` and a key exists (`AVE_EMAIL_API_KEY` or
`RESEND_API_KEY`), from `AVE_EMAIL_FROM`; it keeps the same outbox row
(provider `resend`) as the record of what went out. Any other name, or
resend without a key, falls back to the outbox with a warning.

    Email(to, subject, body, kind, owner=None, workspace_id=None)
    sender_for(name, db, api_key=None, from_addr=None) -> EmailSender
    outbox(db, kind=None, to=None) -> [dict]  newest last
    remember_address(db, owner, email) / address_for(db, owner, fallback=None)
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

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


class ResendEmail(OutboxEmail):
    """Item 7: Resend (POST /emails). A 10 s timeout, and at most two retries
    with backoff on a 5xx, a 429 or a timeout, all under one Idempotency-Key
    so a retry never sends twice. Sending never raises: a failed email is
    logged and recorded in the outbox as `resend (failed)`."""

    name = "resend"
    URL = "https://api.resend.com/emails"
    TIMEOUT = 10.0
    RETRIES = 2

    def __init__(self, db: Database, api_key: str, from_addr: str, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(db)
        self.api_key, self.from_addr = api_key, from_addr
        self.client = client or httpx.Client()
        self.sleep = sleep

    def _post(self, email: Email, key: str) -> bool:
        body = {"from": self.from_addr, "to": [email.to], "subject": email.subject, "text": email.body}
        headers = {"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key}
        for attempt in range(self.RETRIES + 1):
            try:
                r = self.client.post(self.URL, json=body, headers=headers, timeout=self.TIMEOUT)
            except httpx.TransportError as exc:
                why = type(exc).__name__
            else:
                if r.status_code < 300:
                    return True
                if r.status_code < 500 and r.status_code != 429:
                    log.error("email (resend) refused kind=%s status=%s: %s", email.kind, r.status_code, r.text[:200])
                    return False
                why = f"status {r.status_code}"
            if attempt < self.RETRIES:
                self.sleep(0.5 * 2 ** attempt)
        log.error("email (resend) failed kind=%s after %d tries: %s", email.kind, self.RETRIES + 1, why)
        return False

    def send(self, email: Email) -> None:
        sent = self._post(email, f"{email.kind}-{uuid.uuid4().hex}")
        with self.db.tx() as c:
            c.execute("INSERT INTO notify_outbox (workspace_id, owner, to_addr, kind, subject, body, provider, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (email.workspace_id, email.owner, email.to, email.kind, email.subject, email.body,
                       self.name if sent else f"{self.name} (failed)", now_iso()))
            event = SENT_EVENTS.get(email.kind)
            if sent and event and email.owner:
                analytics.safe_in(c, event, email.owner, {"kind": email.kind}, workspace_id=email.workspace_id)
        if sent:
            log.info("email (resend) kind=%s to=%s", email.kind, email.to)


def sender_for(name: str | None, db: Database, api_key: str | None = None, from_addr: str | None = None) -> EmailSender:
    """The outbox, unless `name` is resend and a key exists (env when not given)."""
    name = (name or "outbox").strip().lower()
    if name == "resend":
        key = api_key or os.environ.get("AVE_EMAIL_API_KEY") or os.environ.get("RESEND_API_KEY")
        sender = from_addr or os.environ.get("AVE_EMAIL_FROM") or ""
        if key and sender:
            return ResendEmail(db, key, sender)
        log.warning("email provider resend needs AVE_EMAIL_API_KEY and AVE_EMAIL_FROM; writing emails to the outbox instead")
    elif name not in ("outbox", "fake"):
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
