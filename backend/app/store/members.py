"""G2: workspace members, roles, invites and magic sign-in links.

- **Roles.** Owner (the workspace's `owner`: everything), Editor (everything
  except members and billing), Reviewer (reads, and comments). The owner is
  never a row here; everyone else is one row per workspace.
- **Invites** go by email. The link is `<invite id>.<HMAC over id, email,
  role, expiry>` (the F6 share key), so a copied link cannot be bent to
  another role; the row is always read too, so turning an invite off or
  accepting it once is instant. Invites expire after 14 days.
- **Spend limits.** A member may have a monthly limit; the spend guard
  counts what they caused this month (`usage.by`) against it.
- **Login links** (email sign-in): `<id>.<HMAC over id, email, expiry>`,
  15 minutes, one use.
"""
from __future__ import annotations

import re

import json

import base64
import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from app.store.db import Database
from app.store.workspaces import personal
from app.timefmt import now_iso

ROLES = ("owner", "editor", "reviewer")
MEMBER_ROLES = ("editor", "reviewer")
ROLE_WORDS = {"owner": "Owner", "editor": "Editor", "reviewer": "Reviewer"}
INVITE_DAYS = 14
LOGIN_MINUTES = 15


class MemberError(ValueError):
    """A change that cannot be made; the message is the sentence shown."""


class LinkRefused(ValueError):
    """An invite or login link that does not work; `gone` is True for expired or used."""

    def __init__(self, message: str, gone: bool = False) -> None:
        super().__init__(message)
        self.gone = gone


@dataclass(frozen=True)
class Member:
    workspace_id: str
    member: str
    email: str | None
    name: str | None
    role: str
    spend_limit_usd: float | None
    invited_by: str | None
    joined_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _later(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _mac(key: str, *parts: str) -> str:
    digest = hmac.new(key.encode(), "|".join(parts).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


# Launch item 5: an address becomes an owner id (`email:<address>`) and so a
# storage folder name; only the plain characters real addresses use are
# accepted (no slashes, backslashes, quotes, control characters or `..`).
_EMAIL = re.compile(r"[a-z0-9!#$%&'*+=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+=?^_`{|}~-]+)*"
                    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")


def clean_email(email: str | None) -> str:
    text = (email or "").strip().lower()
    if not text or len(text) > 254 or not _EMAIL.fullmatch(text) or len(text.split("@")[0]) > 64:
        raise MemberError("Enter an email address like name@example.com.")
    return text


def _limit(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0 or value > 100000:
        raise MemberError("A spend limit is between $0 and $100,000 a month, or none.")
    return round(float(value), 2)


# ── workspaces and roles ──

def workspace_of(db: Database, owner: str) -> str:
    with db.tx() as c:
        return personal(c, owner)


def workspace(db: Database, workspace_id: str) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT id, name, owner FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return {"workspace_id": row["id"], "name": row["name"], "owner": row["owner"]} if row else None


def role_in(db: Database, workspace_id: str, user: str) -> str | None:
    """The person's role in the workspace, or None when they are not in it."""
    with db.tx() as c:
        row = c.execute("SELECT owner FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            return None
        if row["owner"] == user:
            return "owner"
        found = c.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND member = ?",
                          (workspace_id, user)).fetchone()
    return found["role"] if found else None


def member(db: Database, workspace_id: str, user: str) -> Member | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM workspace_members WHERE workspace_id = ? AND member = ?", (workspace_id, user)).fetchone()
    return Member(**{k: row[k] for k in row.keys()}) if row else None


def members(db: Database, workspace_id: str) -> list[Member]:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM workspace_members WHERE workspace_id = ? ORDER BY joined_at, member", (workspace_id,)).fetchall()
    return [Member(**{k: r[k] for k in r.keys()}) for r in rows]


def workspaces_for(db: Database, user: str) -> list[dict]:
    """Every workspace the person works in: their own first, then each they joined."""
    with db.tx() as c:
        own = personal(c, user)
        rows = c.execute("SELECT w.id, w.name, w.owner, m.role FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id "
                         "WHERE m.member = ? ORDER BY m.joined_at", (user,)).fetchall()
        mine = c.execute("SELECT name FROM workspaces WHERE id = ?", (own,)).fetchone()
    return [{"workspace_id": own, "name": mine["name"], "role": "owner", "own": True},
            *({"workspace_id": r["id"], "name": r["name"], "role": r["role"], "own": False, "owner": r["owner"]} for r in rows)]


def set_role(db: Database, workspace_id: str, user: str, role: str | None = None,
             spend_limit_usd: float | None = None, clear_limit: bool = False) -> Member:
    if role is not None and role not in MEMBER_ROLES:
        raise MemberError("A member is an Editor or a Reviewer.")
    found = member(db, workspace_id, user)
    if found is None:
        raise MemberError("That person is not in this workspace.")
    new_limit = None if clear_limit else (_limit(spend_limit_usd) if spend_limit_usd is not None else found.spend_limit_usd)
    with db.tx() as c:
        c.execute("UPDATE workspace_members SET role = ?, spend_limit_usd = ? WHERE workspace_id = ? AND member = ?",
                  (role or found.role, new_limit, workspace_id, user))
    return member(db, workspace_id, user)  # type: ignore[return-value]


def remove(db: Database, workspace_id: str, user: str) -> bool:
    with db.tx() as c:
        c.execute("DELETE FROM member_shares WHERE workspace_id = ? AND member = ?", (workspace_id, user))
        return c.execute("DELETE FROM workspace_members WHERE workspace_id = ? AND member = ?", (workspace_id, user)).rowcount > 0


# ── invites ──

def invite(db: Database, key: str, workspace_id: str, email: str, role: str, by: str,
           spend_limit_usd: float | None = None, shares: dict | None = None) -> tuple[dict, str]:
    """A new invite and its link token. One live invite per address: a new
    one turns the older off. `shares` ({"projects": [...], "videos": [...]})
    is what a Reviewer will see once they accept (launch item 1)."""
    if role not in MEMBER_ROLES:
        raise MemberError("Invite someone as an Editor or a Reviewer.")
    address = clean_email(email)
    limit = _limit(spend_limit_usd)
    with db.tx() as c:
        owner = c.execute("SELECT owner FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if owner is None:
            raise MemberError("That workspace does not exist.")
        if c.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND lower(email) = ?", (workspace_id, address)).fetchone():
            raise MemberError(f"{address} is already in this workspace.")
        now = now_iso()
        c.execute("UPDATE workspace_invites SET revoked_at = ? WHERE workspace_id = ? AND email = ? "
                  "AND accepted_at IS NULL AND revoked_at IS NULL", (now, workspace_id, address))
        invite_id = "i" + secrets.token_hex(8)
        c.execute("INSERT INTO workspace_invites (id, workspace_id, email, role, spend_limit_usd, invited_by, created_at, expires_at, shares) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (invite_id, workspace_id, address, role, limit, by, now, _later(days=INVITE_DAYS),
                                                         json.dumps(_clean_shares(shares))))
    row = get_invite(db, invite_id)
    return row, invite_token(key, row)   # type: ignore[arg-type]


def invite_token(key: str, row: dict) -> str:
    return f"{row['id']}.{_mac(key, 'invite', row['id'], row['email'], row['role'], row['expires_at'])}"


def get_invite(db: Database, invite_id: str) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM workspace_invites WHERE id = ?", (invite_id,)).fetchone()
    if row is None:
        return None
    out = {k: row[k] for k in row.keys()}
    out["state"] = ("accepted" if row["accepted_at"] else "revoked" if row["revoked_at"]
                    else "expired" if row["expires_at"] <= now_iso() else "waiting")
    return out


def invites(db: Database, workspace_id: str) -> list[dict]:
    """Invites still waiting (not accepted, not turned off), newest first."""
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM workspace_invites WHERE workspace_id = ? AND accepted_at IS NULL "
                                          "AND revoked_at IS NULL ORDER BY created_at DESC", (workspace_id,))]
    return [i for i in (get_invite(db, x) for x in ids) if i]


def revoke_invite(db: Database, workspace_id: str, invite_id: str) -> bool:
    with db.tx() as c:
        return c.execute("UPDATE workspace_invites SET revoked_at = ? WHERE id = ? AND workspace_id = ? AND accepted_at IS NULL "
                         "AND revoked_at IS NULL", (now_iso(), invite_id, workspace_id)).rowcount > 0


def resolve_invite(db: Database, key: str, token: str | None) -> dict:
    """The invite a link names, checked: signature, then the row."""
    invite_id, _, mac = (token or "").partition(".")
    row = get_invite(db, invite_id) if invite_id and mac else None
    if row is None or not hmac.compare_digest(mac, invite_token(key, row).partition(".")[2]):
        raise LinkRefused("This invite link is not valid. Ask for a new one.")
    if row["state"] == "accepted":
        raise LinkRefused("This invite has already been used.", gone=True)
    if row["state"] == "revoked":
        raise LinkRefused("This invite was turned off. Ask for a new one.", gone=True)
    if row["state"] == "expired":
        raise LinkRefused("This invite has expired. Ask for a new one.", gone=True)
    return row


def accept(db: Database, key: str, token: str | None, user: str, email: str | None, name: str | None) -> Member:
    """Join the workspace the invite names, with its role and limit. The
    owner cannot join their own workspace; someone already in it keeps
    their place (the invite is used up)."""
    row = resolve_invite(db, key, token)
    with db.tx() as c:
        owner = c.execute("SELECT owner FROM workspaces WHERE id = ?", (row["workspace_id"],)).fetchone()
        if owner is None:
            raise LinkRefused("That workspace no longer exists.", gone=True)
        if owner["owner"] == user:
            raise MemberError("This is your own workspace; you are already its Owner.")
        c.execute("INSERT OR IGNORE INTO workspace_members (workspace_id, member, email, name, role, spend_limit_usd, invited_by, joined_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (row["workspace_id"], user, (email or row["email"]).lower(), name, row["role"], row["spend_limit_usd"],
                   row["invited_by"], now_iso()))
        c.execute("UPDATE workspace_invites SET accepted_at = ?, accepted_by = ? WHERE id = ?", (now_iso(), user, row["id"]))
        _add_shares_in(c, row["workspace_id"], user, json.loads(row.get("shares") or "{}"), row["invited_by"])
    return member(db, row["workspace_id"], user)  # type: ignore[return-value]


# ── what a member was shared (launch item 1) ──

def _clean_shares(shares: dict | None) -> dict:
    shares = shares or {}
    return {"projects": sorted({str(x) for x in shares.get("projects") or [] if x}),
            "videos": sorted({str(x) for x in shares.get("videos") or [] if x})}


def _add_shares_in(c, workspace_id: str, user: str, shares: dict, by: str | None) -> None:
    clean = _clean_shares(shares)
    for kind, ids in (("project", clean["projects"]), ("video", clean["videos"])):
        for item in ids:
            c.execute("INSERT OR IGNORE INTO member_shares (workspace_id, member, kind, item_id, shared_by, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?)", (workspace_id, user, kind, item, by, now_iso()))


def shares(db: Database, workspace_id: str, user: str) -> dict:
    """{"projects": [...], "videos": [...]} shared with this member."""
    with db.tx() as c:
        rows = c.execute("SELECT kind, item_id FROM member_shares WHERE workspace_id = ? AND member = ? ORDER BY item_id",
                         (workspace_id, user)).fetchall()
    return {"projects": [r["item_id"] for r in rows if r["kind"] == "project"],
            "videos": [r["item_id"] for r in rows if r["kind"] == "video"]}


def set_shares(db: Database, workspace_id: str, user: str, new: dict, by: str) -> dict:
    """Replace what is shared with a member."""
    with db.tx() as c:
        if not c.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND member = ?", (workspace_id, user)).fetchone():
            raise MemberError("That person is not in this workspace.")
        c.execute("DELETE FROM member_shares WHERE workspace_id = ? AND member = ?", (workspace_id, user))
        _add_shares_in(c, workspace_id, user, new, by)
    return shares(db, workspace_id, user)


def can_see(db: Database, workspace_id: str, user: str, *, video_id: str | None = None, project_id: str | None = None) -> bool:
    """Whether a Reviewer may read this video (shared itself, or its project
    is) or this project (shared itself)."""
    with db.tx() as c:
        if project_id is not None:
            return c.execute("SELECT 1 FROM member_shares WHERE workspace_id = ? AND member = ? AND kind = 'project' AND item_id = ?",
                             (workspace_id, user, project_id)).fetchone() is not None
        if video_id is None:
            return False
        return c.execute(
            "SELECT 1 FROM member_shares s WHERE s.workspace_id = ? AND s.member = ? AND ("
            "(s.kind = 'video' AND s.item_id = ?) OR "
            "(s.kind = 'project' AND s.item_id = (SELECT project_id FROM videos WHERE id = ?)))",
            (workspace_id, user, video_id, video_id)).fetchone() is not None


# ── login links (email sign-in) ──

def login_link(db: Database, key: str, email: str) -> str:
    address = clean_email(email)
    link_id = "l" + secrets.token_hex(10)
    expires = _later(minutes=LOGIN_MINUTES)
    with db.tx() as c:
        c.execute("INSERT INTO login_links (id, email, created_at, expires_at) VALUES (?, ?, ?, ?)", (link_id, address, now_iso(), expires))
    return f"{link_id}.{_mac(key, 'login', link_id, address, expires)}"


def use_login_link(db: Database, key: str, token: str | None) -> str:
    """The email a login link proves, used up; refused when altered, used or old."""
    link_id, _, mac = (token or "").partition(".")
    with db.tx() as c:
        row = c.execute("SELECT * FROM login_links WHERE id = ?", (link_id,)).fetchone() if link_id and mac else None
        if row is None or not hmac.compare_digest(mac, _mac(key, "login", row["id"], row["email"], row["expires_at"])):
            raise LinkRefused("This sign-in link is not valid. Ask for a new one.")
        if row["used_at"]:
            raise LinkRefused("This sign-in link has already been used. Ask for a new one.", gone=True)
        if row["expires_at"] <= now_iso():
            raise LinkRefused("This sign-in link has expired. Ask for a new one.", gone=True)
        c.execute("UPDATE login_links SET used_at = ? WHERE id = ?", (now_iso(), link_id))
    return row["email"]


def owner_for_email(db: Database, email: str) -> str | None:
    """An existing account with this address (remembered at a Google sign-in), so
    signing in by email reaches the same work."""
    with db.tx() as c:
        row = c.execute("SELECT key FROM meta WHERE key LIKE 'notify_email:%' AND lower(value) = ? ORDER BY key LIMIT 1",
                        (email.lower(),)).fetchone()
    return row["key"][len("notify_email:"):] if row else None
