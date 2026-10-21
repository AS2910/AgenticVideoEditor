"""0024 (G2): roles and invites.

    workspace_members   who besides the owner works in a workspace, and as
                        what: Editor or Reviewer (the owner is the
                        workspace's own `owner`, always Owner), with an
                        optional monthly spend limit
    workspace_invites   an invite by email: role, limit, who sent it, when
                        it expires, and whether it was accepted or turned off
    login_links         one row per magic sign-in link sent by email, so each
                        works once
    usage.by            who caused each charge (the signed-in person), so a
                        member's month can be counted against their limit

`down` drops the three tables and the column. Charges keep their amounts;
only the record of which member caused them goes."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id    TEXT NOT NULL,
    member          TEXT NOT NULL,          -- the person's owner id, e.g. google:123 or email:a@b.c
    email           TEXT,
    name            TEXT,
    role            TEXT NOT NULL,          -- editor | reviewer
    spend_limit_usd REAL,
    invited_by      TEXT,
    joined_at       TEXT NOT NULL,
    PRIMARY KEY (workspace_id, member)
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS workspace_members_member ON workspace_members (member)")
    conn.execute("""CREATE TABLE IF NOT EXISTS workspace_invites (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    email           TEXT NOT NULL,
    role            TEXT NOT NULL,
    spend_limit_usd REAL,
    invited_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    accepted_at     TEXT,
    accepted_by     TEXT,
    revoked_at      TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS workspace_invites_ws ON workspace_invites (workspace_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS login_links (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
)""")
    add_column(conn, "usage", "by", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS usage_by ON usage (by, at)")


def down(conn) -> None:
    conn.execute("DROP INDEX IF EXISTS usage_by")
    drop_column(conn, "usage", "by")
    for table, index in (("login_links", None), ("workspace_invites", "workspace_invites_ws"),
                         ("workspace_members", "workspace_members_member")):
        if table in tables(conn):
            if index:
                conn.execute(f"DROP INDEX IF EXISTS {index}")
            conn.execute(f"DROP TABLE {table}")
