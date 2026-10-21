"""0032 (launch, item 5): accounts with a password, and their one-use tokens.

    accounts      one per person who signed up with an email and a password:
                  a stable owner id (`acct:<id>`), the address, the scrypt
                  hash, when the address was verified, a session version
                  (bumped on a password reset or change, signing every other
                  session out) and when the terms were accepted
    auth_tokens   one-use links: verify an address, reset a password, confirm
                  a new address; only a hash of each token is kept

Both live outside any workspace (exempt in 0030). `down` drops them.
"""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
    id               TEXT PRIMARY KEY,
    email            TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    verified_at      TEXT,
    session_version  INTEGER NOT NULL DEFAULT 1,
    terms_version    TEXT,
    terms_at         TEXT,
    created_at       TEXT NOT NULL,
    deleted_at       TEXT
)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash   TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,          -- verify | reset | change_email
    account_id   TEXT NOT NULL,
    email        TEXT NOT NULL,          -- the address the link went to
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    used_at      TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS auth_tokens_by_account ON auth_tokens (account_id, kind)")


def down(conn) -> None:
    have = tables(conn)
    conn.execute("DROP INDEX IF EXISTS auth_tokens_by_account")
    for table in ("auth_tokens", "accounts"):
        if table in have:
            conn.execute(f"DROP TABLE {table}")
