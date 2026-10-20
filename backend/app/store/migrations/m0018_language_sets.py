"""0018 (B2): language sets. A language version is a variant of its master
video, linked to it:

    videos.master_id    the master's id (p<n>), NULL for a master or a plain video
    videos.language     en | hi | hinglish | ta | mr; NULL = the master's own language
    videos.synced_edit  the master's edit marker the child last synced to: the id of
                        the master's newest `edit.shipped` / `edit.undone` event (F7)
                        when the child was made or last synced; 0 = before any

Nothing is backfilled: no video is a language version before this step.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column


def up(conn) -> None:
    add_column(conn, "videos", "master_id", "TEXT")
    add_column(conn, "videos", "language", "TEXT")
    add_column(conn, "videos", "synced_edit", "INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS videos_by_master ON videos (master_id)")


def down(conn) -> None:
    conn.execute("DROP INDEX IF EXISTS videos_by_master")
    drop_column(conn, "videos", "synced_edit")
    drop_column(conn, "videos", "language")
    drop_column(conn, "videos", "master_id")
