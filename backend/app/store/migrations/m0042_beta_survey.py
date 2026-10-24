"""0042 (beta kit): the three questions after a person's first export.

    beta_survey   one row per person (the signed-in owner), made when the
                  questions are first shown, so they are shown once: the
                  workspace, the video just exported, when shown, and once
                  answered: how useful (very | somewhat | not), what almost
                  stopped them (their words, optional) and would they pay
                  (yes | maybe | no), and when.

It carries `workspace_id`, so on Postgres it gets the 0034 RLS policy. `down`
refuses while it holds rows (people's answers would be lost); restore a backup.
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS beta_survey (
    owner           TEXT PRIMARY KEY,       -- the signed-in person; one row each
    workspace_id    TEXT,
    video_id        TEXT,
    shown_at        TEXT NOT NULL,
    useful          TEXT,                   -- very | somewhat | not
    almost_stopped  TEXT,
    would_pay       TEXT,                   -- yes | maybe | no
    answered_at     TEXT
)""")
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        m0034.apply(conn, "beta_survey")


def down(conn) -> None:
    if "beta_survey" not in tables(conn):
        return
    n = conn.execute("SELECT COUNT(*) FROM beta_survey").fetchone()[0]
    if n:
        raise RuntimeError(f"beta_survey holds {n} row(s); refusing to drop it (restore a backup instead)")
    if is_pg(conn):
        conn.execute("DROP POLICY IF EXISTS ws_scope ON beta_survey")
    conn.execute("DROP TABLE beta_survey")
