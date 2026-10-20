"""Workspaces (Step 0, WS): every row of a user's data names the workspace it
belongs to. One workspace per owner for now (their own); reads do not filter
on it until G5 brings members and row-level security."""
from __future__ import annotations

import sqlite3

from app.store.migrations.m0008_workspaces import ensure
from app.timefmt import now_iso


def personal(c: sqlite3.Connection, owner: str) -> str:
    """The owner's own workspace id, made the first time it is needed."""
    return ensure(c, owner, now_iso())


def stamp_last(c: sqlite3.Connection, table: str, video_id: str, folder_id: str | None = None) -> None:
    """Give the row just inserted into `table` its video's workspace (or, for a
    charge with no video, its project's). Call in the same transaction."""
    c.execute(
        f"UPDATE {table} SET workspace_id = COALESCE("
        "(SELECT workspace_id FROM videos WHERE id = ?), (SELECT workspace_id FROM projects WHERE id = ?)) "
        "WHERE rowid = last_insert_rowid()",
        (video_id, folder_id or ""),
    )
