"""0019 (C2): client review. Three tables, all new and empty:

    review_comments  one comment a reviewer (or the owner) left on a video at a
                     time in one of its versions, open or resolved, with its
                     replies as a JSON list [{author_kind, author_name, text, at}]
    notify_queue     what the owner's next digest email will say (a comment, an
                     approval, a change request), until a digest takes it
    notify_outbox    every email the app sent through its email interface; the
                     fake provider (the default, no real email) only writes here
"""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS review_comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    project_id   TEXT,                 -- the video's project (f<n>) when it has one
    video_id     TEXT NOT NULL,
    share_id     TEXT,                 -- the review link it came through; NULL when the owner wrote it
    author_kind  TEXT NOT NULL DEFAULT 'reviewer',   -- reviewer | user
    author_name  TEXT NOT NULL,
    at_s         REAL NOT NULL,        -- seconds into that version's render
    version      INTEGER,              -- the render version it was left on (v3, v4...)
    text         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',       -- open | resolved
    replies      TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    resolved_at  TEXT,
    resolved_by  TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS review_comments_by_video ON review_comments (video_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS review_comments_by_share ON review_comments (share_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS notify_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    owner        TEXT NOT NULL,
    project_id   TEXT,
    video_id     TEXT,
    kind         TEXT NOT NULL,        -- comment | approved | changes_asked
    payload      TEXT NOT NULL DEFAULT '{}',
    at           TEXT NOT NULL,
    digested_at  TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS notify_queue_pending ON notify_queue (owner, digested_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS notify_outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    owner        TEXT,
    to_addr      TEXT NOT NULL,
    kind         TEXT NOT NULL,        -- digest | version_ready | review_invite
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    provider     TEXT NOT NULL,
    created_at   TEXT NOT NULL
)""")


def down(conn) -> None:
    for index in ("review_comments_by_video", "review_comments_by_share", "notify_queue_pending"):
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    for table in ("notify_outbox", "notify_queue", "review_comments"):
        if table in tables(conn):
            conn.execute(f"DROP TABLE {table}")
