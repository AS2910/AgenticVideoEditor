"""0030 (launch, item 1): `workspace_id` on every table that holds a user's
data, defaulting to the owner's workspace.

0008 gave the column to videos, projects and the tables keyed by a video;
the projects plan's later tables mostly carried it. This step adds it to the
owner-keyed tables that did not (billing, credits, invoices, data requests,
error reports, liveness, provenance, spend alerts, notification settings),
backfills each from its owner's workspace, and adds one AFTER INSERT trigger
per table so a row written without a workspace takes its owner's (or, for a
row keyed by a video, its video's). A writer that forgets is therefore safe.

Tables left without the column, on purpose (`EXEMPT`): bookkeeping
(`schema_migrations`, `sqlite_sequence`), the workspaces themselves, stores
keyed by owner in their key (`meta`, `feature_flags`), and rows that exist
before or outside any account (`login_links`, `abuse_reports`, and the
auth tables 0031 adds).

`down` drops the triggers and the added columns.

On Postgres (item 6) each trigger is a BEFORE INSERT function that fills
`NEW.workspace_id` the same way; the outcome is the same row.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables
from app.store.pg import is_pg

# Owner-keyed tables that get the column here (their owner column's name).
ADDED = {
    "billing_accounts": "owner", "credit_grants": "owner", "invoices": "owner",
    "data_requests": "owner", "error_reports": "owner", "liveness_attempts": "owner",
    "provenance_marks": "owner", "spend_alerts": "owner", "notification_settings": "recipient",
}
EXEMPT = frozenset({
    "schema_migrations", "sqlite_sequence", "workspaces", "meta", "feature_flags",
    "login_links", "abuse_reports",
    # 0031 onwards: accounts and their one-use tokens live outside any workspace.
    "accounts", "auth_tokens", "spend_days", "idempotency",
    "waitlist",  # 0035: asked for access, no account yet
    # 0036: the admin's audit trail and suspensions (admin-only, like abuse_reports).
    "admin_audit", "suspensions",
})
# How a table's row finds its owner, in order of preference.
VIDEO_KEYS = ("video_id", "project_id")


def _trigger_name(table: str) -> str:
    return f"ws_default_{table}"


def _owner_column(cols: set[str]) -> str | None:
    for name in ("owner", "recipient"):
        if name in cols:
            return name
    return None


def _source(table: str, cols: set[str]) -> str | None:
    """The SQL expression for the workspace a new row of `table` belongs to."""
    parts = []
    for key in VIDEO_KEYS:
        if key in cols:
            parts.append(f"(SELECT workspace_id FROM videos WHERE id = NEW.{key})")
            parts.append(f"(SELECT workspace_id FROM projects WHERE id = NEW.{key})")
    owner = _owner_column(cols)
    if owner:
        parts.append(f"(SELECT id FROM workspaces WHERE owner = NEW.{owner} ORDER BY created_at, id LIMIT 1)")
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"


def user_tables(conn) -> list[str]:
    return sorted(t for t in tables(conn) if t not in EXEMPT and not t.startswith("sqlite_"))


def up(conn) -> int:
    from app.store.migrations.m0008_workspaces import ensure
    from app.timefmt import now_iso
    for table, owner in ADDED.items():
        if table in tables(conn):
            add_column(conn, table, "workspace_id", "TEXT")
            for (who,) in conn.execute(f"SELECT DISTINCT {owner} FROM {table} WHERE workspace_id IS NULL").fetchall():
                if who and who != "*":
                    ensure(conn, who, now_iso())
            conn.execute(
                f"UPDATE {table} SET workspace_id = (SELECT id FROM workspaces w WHERE w.owner = {table}.{owner} "
                f"ORDER BY w.created_at, w.id LIMIT 1) WHERE workspace_id IS NULL")
    made = 0
    for table in user_tables(conn):
        cols = columns(conn, table)
        source = _source(table, cols)
        if "workspace_id" not in cols or source is None:
            continue
        if is_pg(conn):
            _pg_trigger(conn, table, source)
            made += 1
            continue
        conn.execute(f"DROP TRIGGER IF EXISTS {_trigger_name(table)}")
        conn.execute(
            f"CREATE TRIGGER {_trigger_name(table)} AFTER INSERT ON {table} "
            f"WHEN NEW.workspace_id IS NULL BEGIN "
            f"UPDATE {table} SET workspace_id = {source} WHERE rowid = NEW.rowid; END")
        made += 1
    return made


def _pg_trigger(conn, table: str, source: str) -> None:
    name = _trigger_name(table)
    conn.execute(
        f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $fn$ BEGIN "
        f"IF NEW.workspace_id IS NULL THEN NEW.workspace_id := {source}; END IF; RETURN NEW; END $fn$")
    conn.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    conn.execute(f"CREATE TRIGGER {name} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()")


def down(conn) -> None:
    if is_pg(conn):
        for (name, table) in conn.execute(
                "SELECT DISTINCT name, tbl_name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'ws_default_%'").fetchall():
            conn.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            conn.execute(f"DROP FUNCTION IF EXISTS {name}()")
        for table in ADDED:
            drop_column(conn, table, "workspace_id")
        return
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'ws_default_%'").fetchall():
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table in ADDED:
        drop_column(conn, table, "workspace_id")
