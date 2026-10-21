"""0034 (launch, item 6): row-level security on Postgres. A no-op on SQLite.

Every table with a `workspace_id` column gets RLS enabled and one policy,
`ws_scope`: a row is visible (and writable) when its `workspace_id` equals
the session's `app.workspace_id`, or when the session's `app.bypass_rls` is
`on`. Every connection the app opens sets `app.bypass_rls = on` (see
`app.store.pg.connect`), because the app still scopes rows in code; so today
the policies change nothing.

Turning it into enforcement (SETUP_NEEDED.md, "Postgres"):
1. connect as a role that does not own the tables and is not a superuser
   (owners and superusers skip RLS);
2. per request, inside the transaction:
   `SELECT set_config('app.workspace_id', <id>, true)`;
3. stop setting `app.bypass_rls = on` for request connections (keep it for
   migrations and admin jobs).

A table made later with a `workspace_id` needs the same policy: rerun
`apply(conn)` from that step. `down` drops the policies and disables RLS.
"""
from __future__ import annotations

from app.store.pg import is_pg

POLICY = "ws_scope"


def scoped_tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND column_name = 'workspace_id' ORDER BY table_name").fetchall()]


def apply(conn, table: str) -> None:
    conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    conn.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    conn.execute(
        f"CREATE POLICY {POLICY} ON {table} USING ("
        "current_setting('app.bypass_rls', true) = 'on' "
        "OR workspace_id = current_setting('app.workspace_id', true))")


def up(conn) -> int:
    if not is_pg(conn):
        return 0
    found = scoped_tables(conn)
    for table in found:
        apply(conn, table)
    return len(found)


def down(conn) -> None:
    if not is_pg(conn):
        return
    for table in scoped_tables(conn):
        conn.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        conn.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
