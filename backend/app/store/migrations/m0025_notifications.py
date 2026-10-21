"""0025 (G4): notifications.

    notifications           one row per notification for one person: kind,
                            sentence, detail, where it opens, when read
    notification_settings   per person and kind: in the app, by email
    spend_alerts            each spend threshold (50/80/100%) said once per
                            scope, ceiling and period

`down` drops the three tables (nothing else refers to them)."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT,
    recipient     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    link          TEXT,
    video_id      TEXT,
    project_id    TEXT,
    created_at    TEXT NOT NULL,
    read_at       TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS notifications_recipient ON notifications (recipient, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_settings (
    recipient  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    in_app     INTEGER NOT NULL,
    email      INTEGER NOT NULL,
    PRIMARY KEY (recipient, kind)
)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS spend_alerts (
    owner      TEXT NOT NULL,
    scope      TEXT NOT NULL,
    scope_id   TEXT NOT NULL,
    period     TEXT NOT NULL,
    threshold  INTEGER NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (owner, scope, scope_id, period, threshold)
)""")


def down(conn) -> None:
    for table in ("spend_alerts", "notification_settings", "notifications"):
        if table in tables(conn):
            if table == "notifications":
                conn.execute("DROP INDEX IF EXISTS notifications_recipient")
            conn.execute(f"DROP TABLE {table}")
