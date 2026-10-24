"""0038 (run 4, cost item 1d): paid reads of a clip, kept by its content.

    content_cache   one row per (owner, the media's sha256, kind, key): what a
                    paid read of those exact bytes gave (the transcript, the
                    model's look, its understanding, its reading), as JSON.
                    `key` holds whatever else the read depended on (the model,
                    a hash of the brief and the lines), so a changed brief
                    reads again. The same file uploaded again by the same
                    owner is not paid for twice.

Scoped by owner (one owner's paid work is never served to another) and by
workspace like every user table. `down` drops it; the cache holds nothing
that cannot be read again.
"""
from __future__ import annotations

from app.store.migrations._util import tables
from app.store.pg import is_pg


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS content_cache (
    owner        TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    kind         TEXT NOT NULL,      -- transcript | sight | understanding | reading
    key          TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL,      -- JSON
    workspace_id TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (owner, sha256, kind, key)
)""")
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        m0034.apply(conn, "content_cache")


def down(conn) -> None:
    if "content_cache" not in tables(conn):
        return
    if is_pg(conn):
        conn.execute("DROP POLICY IF EXISTS ws_scope ON content_cache")
    conn.execute("DROP TABLE content_cache")
