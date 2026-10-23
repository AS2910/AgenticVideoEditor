"""0036 (launch rehearsal, item 10): the admin's audit trail and suspensions.

    admin_audit    one row per admin action (grant, refund, suspend, unsuspend,
                   pause, resume, flag change, share take-down, and any later
                   one such as waitlist invites): when, who, what, whose
                   account, the reason and a JSON of details. Append-only:
                   a trigger refuses every UPDATE and DELETE.
    suspensions    one row per suspended owner (why, by whom, since when);
                   unsuspending deletes the row (the audit keeps the history).

Both are admin-only and outside any workspace (exempt in 0030, like
`abuse_reports`), so they carry no `workspace_id` and no RLS policy.

`down` refuses while either table holds rows: the audit is evidence, and
dropping `suspensions` would quietly let suspended people back in. Restore
the pre-update backup instead (RUNBOOK.md, "A bad deploy").
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg

GUARD = "admin_audit_append_only"


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS admin_audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL,          -- the admin's owner id
    action     TEXT NOT NULL,          -- grant | refund | suspend | unsuspend | pause | resume | flag | share_revoke | ...
    target     TEXT,                   -- the owner acted on, when there is one
    reason     TEXT NOT NULL DEFAULT '',
    details    TEXT NOT NULL DEFAULT '{}'
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS admin_audit_by_target ON admin_audit (target, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS suspensions (
    owner        TEXT PRIMARY KEY,
    reason       TEXT NOT NULL,
    suspended_by TEXT NOT NULL,
    suspended_at TEXT NOT NULL
)""")
    if is_pg(conn):
        conn.execute(f"CREATE OR REPLACE FUNCTION {GUARD}() RETURNS trigger LANGUAGE plpgsql AS $fn$ BEGIN "
                     "RAISE EXCEPTION 'admin_audit is append-only'; END $fn$")
        conn.execute(f"DROP TRIGGER IF EXISTS {GUARD} ON admin_audit")
        conn.execute(f"CREATE TRIGGER {GUARD} BEFORE UPDATE OR DELETE ON admin_audit FOR EACH ROW EXECUTE FUNCTION {GUARD}()")
        return
    for verb in ("UPDATE", "DELETE"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {GUARD}_{verb.lower()} BEFORE {verb} ON admin_audit "
                     "BEGIN SELECT RAISE(ABORT, 'admin_audit is append-only'); END")


def down(conn) -> None:
    have = tables(conn)
    for table in ("admin_audit", "suspensions"):
        if table in have:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n:
                raise RuntimeError(f"{table} holds {n} row(s); refusing to drop it (restore a backup instead)")
    if is_pg(conn):
        if "admin_audit" in have:
            conn.execute(f"DROP TRIGGER IF EXISTS {GUARD} ON admin_audit")
        conn.execute(f"DROP FUNCTION IF EXISTS {GUARD}()")
    else:
        for verb in ("update", "delete"):
            conn.execute(f"DROP TRIGGER IF EXISTS {GUARD}_{verb}")
    conn.execute("DROP INDEX IF EXISTS admin_audit_by_target")
    for table in ("admin_audit", "suspensions"):
        if table in have:
            conn.execute(f"DROP TABLE {table}")
