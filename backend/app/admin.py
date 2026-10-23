"""Launch rehearsal item 10: the admin's tools, without the routes.

    audit(db, actor, action, target=None, reason="", details=None)   one append-only row; any admin action calls it
    audit_in(c, ...)                                                  the same inside the caller's transaction
    recent_audit(db, limit=50, target=None) -> [row]                  newest first

    suspend(db, owner, reason, by) / unsuspend(db, owner) -> bool
    suspension(db, owner) -> dict | None                              why and since when, or None
    find(db, q, limit=20) -> [{owner, emails, kinds}]                 by address or owner id, partial

The audit table refuses UPDATE and DELETE (migration 0036). A suspended
owner and anyone acting in their workspace get 403 with SUSPENDED (or
WORKSPACE_SUSPENDED) on every route; their sign-ins are refused, their
share links and media links stop, and paid steps refuse (`AccountSuspended`).
"""
from __future__ import annotations

import json
import logging

from app.errors import NonRetryableError
from app.timefmt import now_iso
from app.usage import SpendCeilingReached

log = logging.getLogger("voltage.admin")

SUSPENDED = "This account is suspended. If you think this is a mistake, reply to any email from Voltage."
WORKSPACE_SUSPENDED = "This workspace is suspended. Switch to your own workspace to carry on."
SHARE_SUSPENDED = "This link is not available right now."
MAX_REASON = 500


class AccountSuspended(SpendCeilingReached):
    """Paid work refused because the owner is suspended (every caller already turns a
    SpendCeilingReached into its sentence, so a running job stops at its next paid step)."""

    scope = "suspended"

    def __init__(self) -> None:
        self.spent = self.ceiling = 0.0
        NonRetryableError.__init__(self, SUSPENDED)


def clean_reason(reason: str | None) -> str:
    return " ".join((reason or "").split())[:MAX_REASON]


def audit_in(c, actor: str, action: str, target: str | None = None, reason: str = "", details: dict | None = None) -> int:
    cur = c.execute("INSERT INTO admin_audit (at, actor, action, target, reason, details) VALUES (?, ?, ?, ?, ?, ?)",
                    (now_iso(), actor, action, target, clean_reason(reason), json.dumps(details or {}, default=str)))
    return int(cur.lastrowid)


def audit(db, actor: str, action: str, target: str | None = None, reason: str = "", details: dict | None = None) -> int:
    """Write one admin action to the audit trail. Never skipped: if this raises, the caller should too."""
    with db.tx() as c:
        return audit_in(c, actor, action, target, reason, details)


def _row(r) -> dict:
    d = dict(r)
    try:
        d["details"] = json.loads(d.get("details") or "{}")
    except ValueError:
        d["details"] = {}
    return d


def recent_audit(db, limit: int = 50, target: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with db.tx() as c:
        if target:
            rows = c.execute("SELECT * FROM admin_audit WHERE target = ? ORDER BY id DESC LIMIT ?", (target, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM admin_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


# ── suspensions ──────────────────────────────────────────────────────────────

def suspension(db, owner: str | None) -> dict | None:
    if not owner:
        return None
    with db.tx() as c:
        r = c.execute("SELECT * FROM suspensions WHERE owner = ?", (owner,)).fetchone()
    return dict(r) if r else None


def any_suspended(db) -> bool:
    with db.tx() as c:
        return c.execute("SELECT 1 FROM suspensions LIMIT 1").fetchone() is not None


def suspend(db, owner: str, reason: str, by: str) -> bool:
    """True when newly suspended, False when they already were (the first reason stays)."""
    with db.tx() as c:
        cur = c.execute("INSERT OR IGNORE INTO suspensions (owner, reason, suspended_by, suspended_at) VALUES (?, ?, ?, ?)",
                        (owner, clean_reason(reason), by, now_iso()))
        return cur.rowcount > 0


def unsuspend(db, owner: str) -> bool:
    with db.tx() as c:
        return c.execute("DELETE FROM suspensions WHERE owner = ?", (owner,)).rowcount > 0


# ── finding people ───────────────────────────────────────────────────────────

def _kind(owner: str) -> str:
    prefix = owner.split(":", 1)[0] if ":" in owner else owner
    return {"acct": "password", "google": "google", "email": "emailed link"}.get(prefix, prefix)


def find(db, q: str, limit: int = 20) -> list[dict]:
    """People whose address or owner id contains `q` (case-insensitive): password
    accounts, addresses remembered at a Google or emailed-link sign-in, members'
    addresses, and owners named by id. One row per owner."""
    needle = (q or "").strip().lower()
    if len(needle) < 2:
        return []
    like = f"%{needle.replace('%', '').replace('_', '')}%"
    found: dict[str, dict] = {}

    def add(owner: str | None, email: str | None, source: str) -> None:
        if not owner:
            return
        row = found.setdefault(owner, {"owner": owner, "emails": [], "kind": _kind(owner), "seen_as": []})
        if email and email.lower() not in row["emails"]:
            row["emails"].append(email.lower())
        if source not in row["seen_as"]:
            row["seen_as"].append(source)

    with db.tx() as c:
        for r in c.execute("SELECT id, email FROM accounts WHERE lower(email) LIKE ? AND deleted_at IS NULL LIMIT 50", (like,)):
            add(f"acct:{r['id']}", r["email"], "account")
        for r in c.execute("SELECT key, value FROM meta WHERE key LIKE 'notify_email:%' AND lower(value) LIKE ? LIMIT 50", (like,)):
            add(r["key"][len("notify_email:"):], r["value"], "signed in")
        for r in c.execute("SELECT member, email FROM workspace_members WHERE lower(email) LIKE ? LIMIT 50", (like,)):
            add(r["member"], r["email"], "member")
        for r in c.execute("SELECT DISTINCT owner FROM workspaces WHERE lower(owner) LIKE ? LIMIT 50", (like,)):
            add(r["owner"], r["owner"][len("email:"):] if r["owner"].startswith("email:") else None, "owner id")
        for owner, row in found.items():
            if not row["emails"]:
                m = c.execute("SELECT value FROM meta WHERE key = ?", (f"notify_email:{owner}",)).fetchone()
                if m:
                    row["emails"].append(m["value"].lower())
    out = sorted(found.values(), key=lambda r: (r["emails"][0] if r["emails"] else r["owner"]))[:limit]
    for row in out:
        row["suspended"] = suspension(db, row["owner"]) is not None
    return out


def emails_of(db, owner: str) -> list[str]:
    out: list[str] = []
    with db.tx() as c:
        if owner.startswith("acct:"):
            r = c.execute("SELECT email FROM accounts WHERE id = ?", (owner[5:],)).fetchone()
            if r:
                out.append(r["email"].lower())
        m = c.execute("SELECT value FROM meta WHERE key = ?", (f"notify_email:{owner}",)).fetchone()
        if m and m["value"].lower() not in out:
            out.append(m["value"].lower())
    if owner.startswith("email:") and owner[6:].lower() not in out:
        out.append(owner[6:].lower())
    return out


# ── who is an admin ──────────────────────────────────────────────────────────

def proven_address(db, owner: str) -> str | None:
    """The address this owner has proven, lower-cased: a password account's only once
    verified; otherwise the one remembered at a Google or emailed-link sign-in."""
    with db.tx() as c:
        if owner.startswith("acct:"):
            r = c.execute("SELECT email FROM accounts WHERE id = ? AND verified_at IS NOT NULL AND deleted_at IS NULL",
                          (owner[5:],)).fetchone()
            return r["email"].lower() if r else None
        m = c.execute("SELECT value FROM meta WHERE key = ?", (f"notify_email:{owner}",)).fetchone()
    if m:
        return m["value"].lower()
    return owner[6:].lower() if owner.startswith("email:") else None


def is_admin_owner(db, owner: str | None, entries: tuple[str, ...]) -> bool:
    if not owner:
        return False
    if owner in entries:
        return True
    addresses = {e.strip().lower() for e in entries if "@" in e and ":" not in e}
    return bool(addresses) and proven_address(db, owner) in addresses


def admin_owner_ids(db, entries: tuple[str, ...]) -> list[str]:
    """Every owner id that is an admin now (for notices): the ids named, and the owners whose
    proven address is named."""
    out = [e for e in entries if "@" not in e or ":" in e]
    addresses = {e.strip().lower() for e in entries if "@" in e and ":" not in e}
    if addresses:
        marks = ",".join("?" for _ in addresses)
        with db.tx() as c:
            found = [f"acct:{r[0]}" for r in c.execute(
                f"SELECT id FROM accounts WHERE lower(email) IN ({marks}) AND verified_at IS NOT NULL AND deleted_at IS NULL",
                tuple(addresses))]
            found += [r[0][len("notify_email:"):] for r in c.execute(
                f"SELECT key FROM meta WHERE key LIKE 'notify_email:%' AND lower(value) IN ({marks})", tuple(addresses))]
        out += found
    return list(dict.fromkeys(out))


def main(argv: list[str] | None = None) -> int:
    """When the admin page cannot be reached (RUNBOOK.md):

        python -m app.admin suspend <owner> --reason "..." --db /data/ave.db
        python -m app.admin unsuspend <owner> --reason "..." --db /data/ave.db
        python -m app.admin find <part of an address> --db /data/ave.db
        python -m app.admin audit [--owner <owner>] --db /data/ave.db

    Each change is audited with the actor `cli:<$USER>`. A suspension made here
    refuses the owner's next request and next paid step at once; jobs already
    running in the server stop at their next paid step."""
    import argparse
    import getpass
    from app.store.db import Database
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="Admin actions without the admin page.")
    parser.add_argument("command", choices=("suspend", "unsuspend", "find", "audit"))
    parser.add_argument("target", nargs="?")
    parser.add_argument("--reason", default="")
    parser.add_argument("--owner", default=None)
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    db = Database(args.db)
    actor = f"cli:{getpass.getuser()}"
    if args.command in ("suspend", "unsuspend"):
        if not args.target:
            parser.error(f"{args.command} needs an owner id")
        if args.command == "suspend":
            if len(clean_reason(args.reason)) < 3:
                parser.error("--reason is required (it goes in the audit trail)")
            if suspend(db, args.target, args.reason, actor):
                audit(db, actor, "suspend", args.target, args.reason, {"from": "cli"})
        elif unsuspend(db, args.target):
            audit(db, actor, "unsuspend", args.target, args.reason, {"from": "cli"})
        print(f"{args.target}: {'suspended' if suspension(db, args.target) else 'not suspended'}")
    elif args.command == "find":
        for row in find(db, args.target or ""):
            flag = "\tSUSPENDED" if row["suspended"] else ""
            print(f"{row['owner']}\t{', '.join(row['emails'])}\t{row['kind']}{flag}")
    else:
        for row in recent_audit(db, 50, target=args.owner):
            print(f"{row['at']}\t{row['actor']}\t{row['action']}\t{row['target'] or '-'}\t{row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
