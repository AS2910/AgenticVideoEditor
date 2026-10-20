"""Share tokens (F6): signed, revocable, expiring links that open one thing
without an account.

A link is `<id>.<signature>`: the row's id and an HMAC-SHA256 (server
secret) over the id with the row's scope, target, role and expiry, so a link
cannot be forged or pointed at something else, and changing the row (say a
later "extend by a week") turns the old link off. The row is always what is
checked: a revoked or expired row refuses with a sentence for whoever
opened it, never a bare 404.

    secret(data_dir, configured)                              -> the server's key
    create(db, key, owner=, project_id=, scope=, target=, role=, days=, name=, by=, data=) -> (Share, token)
    resolve(db, key, token)                                   -> Share, or ShareRefused(code, message)
    revoke(db, share_id, by) / get(db, share_id) / list_for(db, owner, project_id=, scope=, target=)
    token_for(key, share)                                     -> the link's token again (for Copy link)

Scopes: project | video | export (B3). Roles: viewer | reviewer (C2 adds
what a reviewer may do). Each write records its F7 event in its own
transaction. C2 extends this; keep it general.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.store import events
from app.store.actors import user
from app.store.db import Database
from app.timefmt import iso, now_iso

SCOPES = ("project", "video", "export")
ROLES = ("viewer", "reviewer")
DEFAULT_DAYS = 30
MAX_DAYS = 365
SECRET_FILE = "share_secret"

REFUSED = {
    "invalid": "This link is not valid. Check that it was copied in full, or ask for a new one.",
    "revoked": "This link was turned off by the person who shared it. Ask them for a new one.",
    "expired": "This link has expired. Ask the person who shared it for a new one.",
    "gone": "What this link shared has been deleted.",
}


class ShareError(ValueError):
    """A request to make a link that cannot be made, with a sentence to show."""


class ShareRefused(Exception):
    """A link that does not open, with why (`code`) and what to tell its holder."""

    def __init__(self, code: str) -> None:
        super().__init__(REFUSED[code])
        self.code = code
        self.message = REFUSED[code]


@dataclass(frozen=True)
class Share:
    share_id: str
    owner: str
    project_id: str | None
    scope: str
    target: str
    role: str
    name: str | None
    data: dict
    created_by: str
    created_at: str
    expires_at: str
    revoked_at: str | None
    revoked_by: str | None

    def to_dict(self) -> dict:
        return asdict(self)

    def state(self, now: str | None = None) -> str:
        """live | revoked | expired."""
        if self.revoked_at:
            return "revoked"
        return "expired" if self.expires_at <= (now or now_iso()) else "live"


def secret(data_dir: str | Path, configured: str | None = None) -> str:
    """The HMAC key: AVE_SHARE_SECRET when set, else one generated once and
    kept in the data dir (readable by its owner only)."""
    if configured:
        return configured
    path = Path(data_dir) / SECRET_FILE
    if path.exists():
        found = path.read_text().strip()
        if found:
            return found
    path.parent.mkdir(parents=True, exist_ok=True)
    made = secrets.token_hex(32)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(made)
    return made


def _sign(key: str, share_id: str, scope: str, target: str, role: str, expires_at: str) -> str:
    body = "|".join((share_id, scope, target, role, expires_at)).encode()
    digest = hmac.new(key.encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def token_for(key: str, share: Share) -> str:
    return f"{share.share_id}.{_sign(key, share.share_id, share.scope, share.target, share.role, share.expires_at)}"


def _share(row) -> Share:
    return Share(row["id"], row["owner"], row["project_id"], row["scope"], row["target"], row["role"], row["name"],
                 json.loads(row["data"] or "{}"), row["created_by"], row["created_at"], row["expires_at"],
                 row["revoked_at"], row["revoked_by"])


def _expiry(days: float) -> str:
    return iso(datetime.now(timezone.utc) + timedelta(days=days))


def create_in(c: sqlite3.Connection, key: str, *, owner: str, project_id: str | None, scope: str, target: str,
              role: str = "viewer", days: float = DEFAULT_DAYS, name: str | None = None, by: str | None = None,
              data: dict | None = None) -> tuple[Share, str]:
    if scope not in SCOPES:
        raise ShareError(f"A link shares one of: {', '.join(SCOPES)}.")
    if role not in ROLES:
        raise ShareError(f"A link's role is one of: {', '.join(ROLES)}.")
    if not target:
        raise ShareError("Say what the link shares.")
    if not (0 < days <= MAX_DAYS):
        raise ShareError(f"A link lasts between a day and {MAX_DAYS} days.")
    share_id = "sh" + secrets.token_hex(8)
    workspace = None
    if project_id:
        row = c.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        workspace = row[0] if row else None
    clean_name = " ".join((name or "").split())[:80] or None
    c.execute("INSERT INTO share_tokens (id, owner, project_id, scope, target, role, name, data, created_by, created_at, "
              "expires_at, workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (share_id, owner, project_id, scope, target, role, clean_name, json.dumps(data or {}), by or owner,
               now_iso(), _expiry(days), workspace))
    share = get_in(c, share_id)
    assert share is not None
    events.record(c, "share.created", user(by or owner), project_id=project_id,
                  video_id=target if scope == "video" else None, target=share_id,
                  payload={"scope": scope, "target": target, "role": role, "expires_at": share.expires_at, "name": clean_name})
    return share, token_for(key, share)


def create(db: Database, key: str, **kw) -> tuple[Share, str]:
    with db.tx() as c:
        return create_in(c, key, **kw)


def get_in(c: sqlite3.Connection, share_id: str) -> Share | None:
    row = c.execute("SELECT * FROM share_tokens WHERE id = ?", (share_id,)).fetchone()
    return _share(row) if row else None


def get(db: Database, share_id: str) -> Share | None:
    with db.tx() as c:
        return get_in(c, share_id)


def resolve(db: Database, key: str, token: str) -> Share:
    """The live share a link opens, or ShareRefused saying why not. The
    signature is checked before the row is trusted, in constant time."""
    share_id, _, sig = (token or "").partition(".")
    if not share_id or not sig or len(token) > 200:
        raise ShareRefused("invalid")
    share = get(db, share_id)
    if share is None:
        raise ShareRefused("invalid")
    want = _sign(key, share.share_id, share.scope, share.target, share.role, share.expires_at)
    if not hmac.compare_digest(want, sig):
        raise ShareRefused("invalid")
    state = share.state()
    if state != "live":
        raise ShareRefused(state)
    return share


def revoke(db: Database, share_id: str, by: str) -> Share | None:
    """Turn a link off for good (a second revoke changes nothing). None when there is no such link."""
    with db.tx() as c:
        share = get_in(c, share_id)
        if share is None:
            return None
        if share.revoked_at:
            return share
        c.execute("UPDATE share_tokens SET revoked_at = ?, revoked_by = ? WHERE id = ?", (now_iso(), by, share_id))
        events.record(c, "share.revoked", user(by), project_id=share.project_id,
                      video_id=share.target if share.scope == "video" else None, target=share_id,
                      payload={"scope": share.scope, "target": share.target})
        return get_in(c, share_id)


def list_for(db: Database, owner: str, project_id: str | None = None, scope: str | None = None,
             target: str | None = None) -> list[Share]:
    """The owner's links, newest first, narrowed by project, scope and target."""
    sql, args = "SELECT * FROM share_tokens WHERE owner = ?", [owner]
    for column, value in (("project_id", project_id), ("scope", scope), ("target", target)):
        if value is not None:
            sql += f" AND {column} = ?"
            args.append(value)
    with db.tx() as c:
        rows = c.execute(sql + " ORDER BY created_at DESC, id", args).fetchall()
    return [_share(r) for r in rows]
