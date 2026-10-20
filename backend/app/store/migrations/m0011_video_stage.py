"""0011 (F5): a video's stage, Draft by default, and the log of every move
(who, when, from, to, why). `stage_log` is where moves are kept until the
activity log (F7) exists to hold them."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables


def up(conn) -> None:
    add_column(conn, "videos", "stage", "TEXT NOT NULL DEFAULT 'draft'")
    conn.execute("""CREATE TABLE IF NOT EXISTS stage_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     TEXT NOT NULL,
    from_stage   TEXT NOT NULL,
    to_stage     TEXT NOT NULL,
    actor_kind   TEXT NOT NULL,        -- user | voltage | reviewer
    actor_name   TEXT NOT NULL,
    why          TEXT NOT NULL,
    at           TEXT NOT NULL,
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS stage_log_by_video ON stage_log (video_id, id)")


def down(conn) -> None:
    if "stage_log" in tables(conn):
        conn.execute("DROP INDEX IF EXISTS stage_log_by_video")
        conn.execute("DROP TABLE stage_log")
    drop_column(conn, "videos", "stage")
