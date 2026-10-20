"""0013 (F8): soft delete. `deleted_at` and `deleted_by` on videos and
projects (a deleted row is hidden from every list and get, and kept for the
Bin until the purge); `purged_items` remembers the name and owner of each
item the purge removed, so the charges it leaves keep their name.

A voice of one's own lives in `meta` (`my_voices:<owner>`, a JSON list):
its entry carries `deleted_at`/`deleted_by` instead; no schema for it.

`down` refuses while any row is soft-deleted or purged: dropping the columns
would bring deleted items back as live, and the names of purged ones would
be lost. Restore or purge them first."""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables

SOFT = ("videos", "projects")


def up(conn) -> None:
    for table in SOFT:
        add_column(conn, table, "deleted_at", "TEXT")
        add_column(conn, table, "deleted_by", "TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS purged_items (
    kind         TEXT NOT NULL,        -- video | project | voice
    item_id      TEXT NOT NULL,
    name         TEXT NOT NULL,        -- what the Usage page calls it
    owner        TEXT NOT NULL,
    project_id   TEXT,                 -- a video's project when it was deleted
    workspace_id TEXT,
    deleted_at   TEXT,
    purged_at    TEXT NOT NULL,
    PRIMARY KEY (kind, item_id)
)""")


def down(conn) -> None:
    for table in SOFT:
        if "deleted_at" in columns(conn, table):
            n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NOT NULL").fetchone()[0]
            if n:
                raise RuntimeError(f"{n} deleted row(s) in {table} would come back as live; restore or purge them first")
    if "purged_items" in tables(conn):
        if conn.execute("SELECT COUNT(*) FROM purged_items").fetchone()[0]:
            raise RuntimeError("purged_items holds the names of purged items; refusing to drop it")
        conn.execute("DROP TABLE purged_items")
    for table in reversed(SOFT):
        drop_column(conn, table, "deleted_by")
        drop_column(conn, table, "deleted_at")
