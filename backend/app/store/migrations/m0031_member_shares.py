"""0031 (launch, item 1): what a Reviewer may see.

    member_shares        one row per project or video shared with a member
                         of a workspace (a Reviewer reads only these; a
                         video in a shared project counts as shared)
    workspace_invites.shares   the projects and videos an invite shares, as
                         JSON, copied into member_shares on accept

`down` drops both.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS member_shares (
    workspace_id TEXT NOT NULL,
    member       TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- project | video
    item_id      TEXT NOT NULL,
    shared_by    TEXT,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, member, kind, item_id)
)""")
    if "workspace_invites" in tables(conn):
        add_column(conn, "workspace_invites", "shares", "TEXT")


def down(conn) -> None:
    drop_column(conn, "workspace_invites", "shares")
    if "member_shares" in tables(conn):
        conn.execute("DROP TABLE member_shares")
