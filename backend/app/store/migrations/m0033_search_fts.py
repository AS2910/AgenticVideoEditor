"""0033 (launch hardening, 9d): an FTS5 index for Home search.

    search_fts(kind, item_id, owner, workspace_id, body)   tokenize trigram

One row per project (`kind` 'project': its name and brief) and per video
(`kind` 'video': its file name and the words of its transcript). The
trigram tokenizer matches substrings, which is what search does today
(`ql in name.lower()`), so the index can narrow the rows search reads
without changing what it finds: `app.store.home.search` still runs its own
exact checks on the rows the index returns.

Kept in step by triggers on `projects` and `videos` (insert, update of the
indexed columns, delete). Deleted and archived items stay in the index;
search filters them as before. `kind`, `item_id`, `owner` and
`workspace_id` are UNINDEXED: stored, never matched. `workspace_id` keeps
the launch rule that every table of user data names its workspace (FTS5's
own shadow tables, `search_fts_data` and the rest, are system tables).

`down` drops the triggers and the table (the index holds nothing that is
not in `projects` and `videos`).
"""
from __future__ import annotations

from app.store.migrations._util import tables

TABLE = "search_fts"
TRIGGERS = ("search_fts_project_ins", "search_fts_project_upd", "search_fts_project_del",
            "search_fts_video_ins", "search_fts_video_upd", "search_fts_video_del")

# The text indexed for a row, as SQL over NEW: what `home.search` reads.
_PROJECT_BODY = "COALESCE(NEW.name, '') || char(10) || COALESCE(NEW.brief, '')"
_VIDEO_BODY = ("COALESCE(CASE WHEN json_valid(NEW.source) THEN json_extract(NEW.source, '$.filename') END, NEW.id, '')"
               " || char(10) || COALESCE(CASE WHEN json_valid(NEW.transcript) THEN"
               " (SELECT group_concat(json_extract(w.value, '$.text'), ' ') FROM json_each(NEW.transcript, '$.words') AS w)"
               " END, '')")


def available(conn) -> bool:
    return TABLE in tables(conn)


def _insert(kind: str, body: str) -> str:
    return (f"INSERT INTO {TABLE} (kind, item_id, owner, workspace_id, body) "
            f"VALUES ('{kind}', NEW.id, NEW.owner, NEW.workspace_id, {body});")


def _delete(kind: str) -> str:
    return f"DELETE FROM {TABLE} WHERE kind = '{kind}' AND item_id = OLD.id;"


def up(conn) -> None:
    from app.store.pg import is_pg
    if is_pg(conn):
        return          # SQLite FTS5 only; on Postgres search reads every row (home._candidates)
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING fts5("
                 "kind UNINDEXED, item_id UNINDEXED, owner UNINDEXED, workspace_id UNINDEXED, body, "
                 "tokenize = 'trigram')")
    for kind, table, body, cols in (("project", "projects", _PROJECT_BODY, "name, brief, owner, workspace_id"),
                                    ("video", "videos", _VIDEO_BODY, "source, transcript, owner, workspace_id")):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS search_fts_{kind}_ins AFTER INSERT ON {table} "
                     f"BEGIN {_insert(kind, body)} END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS search_fts_{kind}_upd AFTER UPDATE OF {cols} ON {table} "
                     f"BEGIN {_delete(kind)} {_insert(kind, body)} END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS search_fts_{kind}_del AFTER DELETE ON {table} "
                     f"BEGIN {_delete(kind)} END")
    # Backfill: rebuild from the tables as they are (idempotent).
    conn.execute(f"DELETE FROM {TABLE}")
    for kind, table, body in (("project", "projects", _PROJECT_BODY), ("video", "videos", _VIDEO_BODY)):
        conn.execute(f"INSERT INTO {TABLE} (kind, item_id, owner, workspace_id, body) "
                     f"SELECT '{kind}', NEW.id, NEW.owner, NEW.workspace_id, {body} FROM {table} AS NEW")


def down(conn) -> None:
    from app.store.pg import is_pg
    if is_pg(conn):
        return
    for name in TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
