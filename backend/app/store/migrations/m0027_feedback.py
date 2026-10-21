"""0027 (G8): feedback and error reports.

    feedback       a thumb up or down, with an optional reason, on a take (a
                   proposal's candidate) or a turn (Voltage's reply); one per
                   person and target, the latest wins
    error_reports  what the error hook caught, from the browser or the server,
                   with where and a little context

`down` drops both tables (nothing refers to them)."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT,
    owner         TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    target        TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    vote          TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    at            TEXT NOT NULL,
    UNIQUE (owner, video_id, target, target_id)
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS feedback_by_video ON feedback (video_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS error_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT,
    source     TEXT NOT NULL,
    message    TEXT NOT NULL,
    stack      TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    context    TEXT NOT NULL DEFAULT '{}',
    at         TEXT NOT NULL
)""")


def down(conn) -> None:
    for table in ("error_reports", "feedback"):
        if table in tables(conn):
            if table == "feedback":
                conn.execute("DROP INDEX IF EXISTS feedback_by_video")
            conn.execute(f"DROP TABLE {table}")
