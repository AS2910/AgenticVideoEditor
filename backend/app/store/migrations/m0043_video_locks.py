"""0043 (one edit at a time per video): the video lock.

    video_locks   one row per video while something changes it (a Voltage
                  turn, also while it waits for the user's go; an Add, a
                  Discard, an undo...): who holds it (a turn id, a job id, or
                  a request's own id), what it is doing in words ("Adding
                  'Fresh every morning'"), the person who started it and their
                  name, the tab it came from, when it started and when its
                  lease runs out. `stoppable` is 0 for an undo once it started.
                  `snapshot` is the edit set as it stood before an Add or a
                  turn changed it (JSON), so Stop can put it back exactly.

No row means the video is Ready. A lease not renewed by then (the server
died mid-action) is cleared by the stuck-job sweep. It carries `workspace_id`,
so on Postgres it gets the 0034 RLS policy. `down` drops it: a lock is never
data worth keeping (a restart clears them anyway).
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS video_locks (
    video_id          TEXT PRIMARY KEY,
    holder            TEXT NOT NULL,      -- a turn id, a job id, or a request's id (req-...)
    action            TEXT NOT NULL,      -- "Adding 'Fresh every morning'", "Voltage is planning"
    started_by        TEXT,               -- the person (the signed-in user, not the workspace)
    started_by_name   TEXT,
    tab               TEXT,               -- the browser tab it came from (X-Voltage-Tab)
    started_at        TEXT NOT NULL,
    lease_expires_at  REAL NOT NULL,      -- epoch seconds
    stoppable         INTEGER NOT NULL DEFAULT 1,
    snapshot          TEXT,               -- JSON: the edit set before the action changed it
    workspace_id      TEXT
)""")
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        m0034.apply(conn, "video_locks")


def down(conn) -> None:
    if "video_locks" not in tables(conn):
        return
    if is_pg(conn):
        conn.execute("DROP POLICY IF EXISTS ws_scope ON video_locks")
    conn.execute("DROP TABLE video_locks")
