"""0037 (launch rehearsal, item 11): "Send feedback" from the help menu.

    beta_feedback   one row per message: who sent it (the signed-in person) and
                    in which workspace, the words, where they were (route, open
                    video, last job), the app version and user agent, an optional
                    screenshot (its sha256 and type in the artifact store, under
                    `beta-feedback/`), and its status for the admins:
                    new | seen | done (who moved it, when).

It carries `workspace_id`, so on Postgres it gets the 0034 RLS policy. `down`
refuses while it holds rows (people's words would be lost); restore a backup.
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS beta_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT,
    owner           TEXT NOT NULL,          -- the signed-in person who sent it
    message         TEXT NOT NULL,
    route           TEXT NOT NULL DEFAULT '',
    video_id        TEXT,
    job_id          TEXT,
    app_version     TEXT NOT NULL DEFAULT '',
    user_agent      TEXT NOT NULL DEFAULT '',
    screenshot_sha  TEXT,
    screenshot_type TEXT,
    status          TEXT NOT NULL DEFAULT 'new',   -- new | seen | done
    status_by       TEXT,
    status_at       TEXT,
    created_at      TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS beta_feedback_by_status ON beta_feedback (status, id)")
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        m0034.apply(conn, "beta_feedback")


def down(conn) -> None:
    if "beta_feedback" not in tables(conn):
        return
    n = conn.execute("SELECT COUNT(*) FROM beta_feedback").fetchone()[0]
    if n:
        raise RuntimeError(f"beta_feedback holds {n} message(s); refusing to drop it (restore a backup instead)")
    if is_pg(conn):
        conn.execute("DROP POLICY IF EXISTS ws_scope ON beta_feedback")
    conn.execute("DROP INDEX IF EXISTS beta_feedback_by_status")
    conn.execute("DROP TABLE beta_feedback")
