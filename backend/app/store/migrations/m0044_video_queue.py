"""0044 (one edit at a time per video): Up next, the changes waiting on a busy video.

    video_queue   one row per change asked for while the video was Working:
                  `kind` is goal (words for Voltage) or action (a control
                  pressed: Add it, Discard...), `payload` what it needs (JSON),
                  `label` the words the chip shows ("Add line 3"), `position`
                  its place in line, `created_by` the person, `status`
                  queued | running | done | failed | removed, and once it ran,
                  `error` (why it failed) and `finished_at`.

At most three wait per video (the API refuses a fourth). It carries
`workspace_id`, so on Postgres it gets the 0034 RLS policy. `down` drops it:
what waited is lost, nothing in a video is.
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS video_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- goal | action
    payload       TEXT NOT NULL,          -- JSON
    label         TEXT NOT NULL,
    position      INTEGER NOT NULL,
    created_by    TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed | removed
    error         TEXT,
    created_at    TEXT NOT NULL,
    finished_at   TEXT,
    workspace_id  TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS video_queue_by_video ON video_queue (video_id, status, position)")
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        m0034.apply(conn, "video_queue")


def down(conn) -> None:
    if "video_queue" not in tables(conn):
        return
    if is_pg(conn):
        conn.execute("DROP POLICY IF EXISTS ws_scope ON video_queue")
    conn.execute("DROP INDEX IF EXISTS video_queue_by_video")
    conn.execute("DROP TABLE video_queue")
