"""Small helpers the steps share. They work on SQLite and on Postgres (where
`app.store.pg` reads `sqlite_master` and `PRAGMA table_info` from the
information schema)."""
from __future__ import annotations

import sqlite3


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    """ALTER TABLE ADD COLUMN unless it is already there. True when added."""
    if column in columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def drop_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """The reverse of add_column (SQLite 3.35+). True when dropped."""
    if table not in tables(conn) or column not in columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    return True
