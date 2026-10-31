"""0055 (voice consent V1, step 5): the public-figure block's records.

`no_go_voices` (0048) gains what an entry was made from:

    model        the speaker model its `reference_embedding` came from (a vector
                 from another model cannot be compared with it)
    source       upload | export: an admin's clip, or a reported export's file
    source_ref   the clip's file name, or the export's mark (and the abuse report)
    seconds      how much audio the embedding was made from

and two tables:

    no_go_checks   every comparison made when someone clones: who, which video
                   and speaker, the verdict (pass | block | review), how it was
                   decided (voice | name | approved | rejected | unmeasured |
                   vendor), the closest entry and its score, every score (JSON)
    no_go_holds    the borderline queue: a clone from 0.84 to 0.92 of an entry
                   (or one that could not be measured) waits here for an admin.
                   `subject` is what an approval covers (the video's speaker, or
                   an uploaded recording's sha256); the clip is kept only while
                   it waits (`audio_path`) and deleted once decided

Numbered 0055, not the next free number, so the steps built the same night can
each take their own (gaps are allowed). Both tables carry `workspace_id` and get
0034's RLS policy on Postgres. `down` refuses while either holds rows or an entry
carries a model (restore a backup instead).
"""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables
from app.store.pg import is_pg

COLUMNS = (("model", "TEXT NOT NULL DEFAULT ''"), ("source", "TEXT NOT NULL DEFAULT ''"),
           ("source_ref", "TEXT NOT NULL DEFAULT ''"), ("seconds", "REAL"))
TABLES = {
    "no_go_checks": """CREATE TABLE IF NOT EXISTS no_go_checks (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT,
    owner         TEXT NOT NULL,
    video_id      TEXT,
    speaker_label TEXT,
    speaker_name  TEXT,
    verdict       TEXT NOT NULL,                  -- pass | block | review
    how           TEXT NOT NULL,                  -- voice | name | approved | rejected | unmeasured | vendor
    no_go_id      TEXT,                           -- the closest entry (or the one that decided)
    no_go_name    TEXT,
    score         REAL,
    scores        TEXT NOT NULL DEFAULT '[]',     -- JSON [{id, name, score}], every entry compared
    model         TEXT NOT NULL DEFAULT '',
    hold_id       TEXT,
    created_at    TEXT NOT NULL
)""",
    "no_go_holds": """CREATE TABLE IF NOT EXISTS no_go_holds (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT,
    owner         TEXT NOT NULL,
    video_id      TEXT,
    speaker_label TEXT,
    speaker_name  TEXT,
    subject       TEXT NOT NULL,                  -- what an approval covers: video:<id>:<label> or audio:<sha256>
    no_go_id      TEXT,                           -- NULL: the voice could not be measured
    no_go_name    TEXT,
    score         REAL,
    model         TEXT NOT NULL DEFAULT '',
    audio_path    TEXT,                           -- the clip, while it waits; NULL once decided
    status        TEXT NOT NULL,                  -- waiting | approved | rejected | closed
    reason        TEXT NOT NULL DEFAULT '',
    decided_by    TEXT,
    decided_at    TEXT,
    created_at    TEXT NOT NULL
)""",
}
INDEXES = (
    "CREATE INDEX IF NOT EXISTS no_go_checks_by_owner ON no_go_checks (owner, created_at)",
    "CREATE INDEX IF NOT EXISTS no_go_holds_by_status ON no_go_holds (status, created_at)",
    "CREATE INDEX IF NOT EXISTS no_go_holds_by_subject ON no_go_holds (owner, subject, no_go_id)",
)


def up(conn) -> None:
    if "no_go_voices" in tables(conn):
        for name, definition in COLUMNS:
            add_column(conn, "no_go_voices", name, definition)
    for ddl in TABLES.values():
        conn.execute(ddl)
    for ddl in INDEXES:
        conn.execute(ddl)
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        for table in TABLES:
            m0034.apply(conn, table)


def down(conn) -> None:
    there = tables(conn)
    for table in TABLES:
        if table in there:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n:
                raise RuntimeError(f"{table} holds {n} row(s); refusing to drop it (restore a backup instead)")
    if "no_go_voices" in there:
        n = conn.execute("SELECT COUNT(*) FROM no_go_voices").fetchone()[0]
        if n:
            raise RuntimeError(f"no_go_voices holds {n} entr(ies) with their model; refusing (restore a backup instead)")
    for ddl in INDEXES:
        conn.execute("DROP INDEX IF EXISTS " + ddl.split(" IF NOT EXISTS ")[1].split(" ON ")[0])
    for table in TABLES:
        if table in there:
            if is_pg(conn):
                conn.execute(f"DROP POLICY IF EXISTS ws_scope ON {table}")
            conn.execute(f"DROP TABLE {table}")
    for name, _ in COLUMNS:
        drop_column(conn, "no_go_voices", name)
