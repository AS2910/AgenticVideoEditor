"""0035 (launch rehearsal, item 8): the waitlist behind "Request access".

    waitlist   one row per address that asked for access: the address
               (lower case, unique), an optional name and what they make,
               when they asked, and, once an admin sends an invite, who
               sent it and when. An invited address may sign up while
               `launch.invite_only` is on (`accounts_api.may_join`).

It lives outside any workspace (rows come before an account exists; exempt
in 0030). `down` drops it.
"""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS waitlist (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT NOT NULL UNIQUE,
    name         TEXT,
    use_case     TEXT,
    created_at   TEXT NOT NULL,
    invited_at   TEXT,
    invited_by   TEXT
)""")


def down(conn) -> None:
    if "waitlist" in tables(conn):
        conn.execute("DROP TABLE waitlist")
