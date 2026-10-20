"""0021 (D4): pins and archived projects.

    pins                    what each user pinned to the top of Home's
                            sidebar: (owner, kind project|video, item_id)
    projects.archived_at    set while a project is archived (hidden from
    projects.archived_by    Home, searchable, read-only); who archived it

`down` refuses while a project is archived: dropping the columns would make
it writable and visible again without anyone choosing that. Pins are a
convenience and go with the table."""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS pins (
    owner        TEXT NOT NULL,
    kind         TEXT NOT NULL,        -- project | video
    item_id      TEXT NOT NULL,
    pinned_at    TEXT NOT NULL,
    workspace_id TEXT,
    PRIMARY KEY (owner, kind, item_id)
)""")
    add_column(conn, "projects", "archived_at", "TEXT")
    add_column(conn, "projects", "archived_by", "TEXT")


def down(conn) -> None:
    if "archived_at" in columns(conn, "projects"):
        n = conn.execute("SELECT COUNT(*) FROM projects WHERE archived_at IS NOT NULL").fetchone()[0]
        if n:
            raise RuntimeError(f"{n} archived project(s) would become live; unarchive them first")
    drop_column(conn, "projects", "archived_by")
    drop_column(conn, "projects", "archived_at")
    if "pins" in tables(conn):
        conn.execute("DROP TABLE pins")
