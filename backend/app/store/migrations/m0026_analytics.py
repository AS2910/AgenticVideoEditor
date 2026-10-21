"""0026 (G7): analytics events.

    analytics_events   one row per tracked step: its name (from the allow-list
                       in app/analytics.py), the owner it belongs to, the
                       workspace, JSON props, server or client, when

`down` drops the table and its indexes (nothing refers to it)."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS analytics_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT,
    owner         TEXT NOT NULL,
    name          TEXT NOT NULL,
    props         TEXT NOT NULL DEFAULT '{}',
    source        TEXT NOT NULL DEFAULT 'server',
    at            TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS analytics_by_name ON analytics_events (name, at)")
    conn.execute("CREATE INDEX IF NOT EXISTS analytics_by_owner ON analytics_events (owner, name)")


def down(conn) -> None:
    if "analytics_events" in tables(conn):
        conn.execute("DROP INDEX IF EXISTS analytics_by_name")
        conn.execute("DROP INDEX IF EXISTS analytics_by_owner")
        conn.execute("DROP TABLE analytics_events")
