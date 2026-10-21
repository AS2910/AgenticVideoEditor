"""The migration runner (Step 0, M0): applies the numbered steps in
`app.store.migrations` and records them in `schema_migrations`.

`Database` runs `up` at startup. From the command line, against a file or a
Postgres URL (`--db postgres://user:pass@host:5432/name`):

    python -m app.store.migrate status --db var/ave.db
    python -m app.store.migrate up [N] --db var/ave.db      # all pending, or the next N
    python -m app.store.migrate down [N] --db var/ave.db    # the last N applied (default 1)

Each step runs in its own transaction: a step that fails leaves the database
as it was before that step, and nothing after it runs.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any

from app.store.migrations import Migration, all_migrations

TABLE = "schema_migrations"


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
)""")


def applied(conn: sqlite3.Connection) -> dict[int, str]:
    """version -> when it was applied."""
    _ensure(conn)
    return {r[0]: r[1] for r in conn.execute(f"SELECT version, applied_at FROM {TABLE} ORDER BY version")}


def status(conn: sqlite3.Connection) -> list[dict]:
    done = applied(conn)
    return [{"version": m.version, "name": m.name, "applied_at": done.get(m.version)} for m in all_migrations()]


def _run(conn: sqlite3.Connection, migration: Migration, direction: str) -> Any:
    from app.timefmt import now_iso
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Another process (a second server, the CLI) may have run it since we looked.
        there = conn.execute(f"SELECT 1 FROM {TABLE} WHERE version = ?", (migration.version,)).fetchone()
        if (direction == "up") == bool(there):
            conn.execute("ROLLBACK")
            return None
        if direction == "up":
            result = migration.up(conn)
            conn.execute(f"INSERT INTO {TABLE} (version, name, applied_at) VALUES (?, ?, ?)",
                         (migration.version, migration.name, now_iso()))
        else:
            result = migration.down(conn)
            conn.execute(f"DELETE FROM {TABLE} WHERE version = ?", (migration.version,))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return result


def up(conn: sqlite3.Connection, steps: int | None = None) -> dict[int, Any]:
    """Apply the pending steps in order (all, or the next `steps`). Returns
    each applied version's result. A database made before the runner has no
    record yet: its steps run, change nothing (every `up` is idempotent),
    and are recorded."""
    done = applied(conn)
    pending = [m for m in all_migrations() if m.version not in done]
    if steps is not None:
        pending = pending[:steps]
    return {m.version: _run(conn, m, "up") for m in pending}


def down(conn: sqlite3.Connection, steps: int = 1) -> list[int]:
    """Roll back the last `steps` applied steps, newest first."""
    done = applied(conn)
    by_version = {m.version: m for m in all_migrations()}
    rolled = []
    for version in sorted(done, reverse=True)[:steps]:
        if version not in by_version:
            raise RuntimeError(f"migration {version} is applied but this code does not know it")
        _run(conn, by_version[version], "down")
        rolled.append(version)
    return rolled


def down_to(conn: sqlite3.Connection, version: int) -> list[int]:
    """Roll back every applied step after `version` (numbers can have gaps)."""
    return down(conn, sum(1 for v in applied(conn) if v > version))


def connect(path: str) -> sqlite3.Connection:
    from app.store import pg
    if pg.is_url(path):
        return pg.connect(path)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.store.migrate", description="Apply or roll back schema migrations.")
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument("steps", nargs="?", type=int, help="how many steps (up: default all pending; down: default 1)")
    parser.add_argument("--db", required=True, help="path to the SQLite file, or a postgres:// URL")
    args = parser.parse_args(argv)
    conn = connect(args.db)
    try:
        if args.command == "up":
            for version in up(conn, args.steps):
                print(f"applied {version:04d}")
        elif args.command == "down":
            for version in down(conn, 1 if args.steps is None else args.steps):
                print(f"rolled back {version:04d}")
        for row in status(conn):
            mark = row["applied_at"] or "pending"
            print(f"{row['version']:04d} {row['name']:<28} {mark}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
