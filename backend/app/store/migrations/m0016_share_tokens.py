"""0016 (F6): share tokens. One row per link someone made: what it opens
(a project, a video or an export), with which role (viewer or reviewer),
until when, and whether it was turned off. The link itself carries the row's
id and an HMAC over it (app/store/shares.py); the row is what is checked."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS share_tokens (
    id           TEXT PRIMARY KEY,     -- sh<random>, the part of the link before the signature
    owner        TEXT NOT NULL,
    project_id   TEXT,                 -- the project it belongs to (f<n>), for the feed and the purge
    scope        TEXT NOT NULL,        -- project | video | export
    target       TEXT NOT NULL,        -- the project's, video's or export's id
    role         TEXT NOT NULL,        -- viewer | reviewer
    name         TEXT,                 -- who it is for, optional
    data         TEXT NOT NULL DEFAULT '{}',   -- JSON: what a later item needs (C2: allow_download)
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT,
    revoked_by   TEXT,
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS share_tokens_by_target ON share_tokens (scope, target)")
    conn.execute("CREATE INDEX IF NOT EXISTS share_tokens_by_project ON share_tokens (project_id)")


def down(conn) -> None:
    for index in ("share_tokens_by_target", "share_tokens_by_project"):
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    if "share_tokens" in tables(conn):
        conn.execute("DROP TABLE share_tokens")
