"""Launch item 11: prove the migrations on a copy of a real database.

    python -m app.tools.migration_check --db backend/var/ave.db [--since 29]

Copies the database (sqlite3's online backup, so a running server is fine)
into a temp dir and never touches the original. On the copy: every pending
step up; every step after `--since` down, then up again. Each table's row
count must be the same after each round trip, and the copy must pass
PRAGMA integrity_check. Exits 1 with the reason on any difference.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from app.store import migrate


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations' "
        "AND name NOT LIKE 'search_fts%'")]
    return {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in sorted(names)}


def check(source: Path, since: int) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "ave.db"
        with sqlite3.connect(source) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        conn = migrate.connect(str(copy))
        try:
            applied = migrate.up(conn)
            print(f"up: applied {sorted(applied) or 'nothing (already current)'}")
            before = _counts(conn)
            rolled = migrate.down_to(conn, since)
            print(f"down to {since:04d}: rolled back {rolled}")
            again = migrate.up(conn)
            print(f"up again: applied {sorted(again)}")
            after = _counts(conn)
            for table in sorted(set(before) | set(after)):
                if before.get(table) != after.get(table):
                    problems.append(f"{table}: {before.get(table)} rows before, {after.get(table)} after the round trip")
            missing = [m["version"] for m in migrate.status(conn) if not m["applied_at"]]
            if missing:
                problems.append(f"not applied after the round trip: {missing}")
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                problems.append(f"integrity_check: {ok}")
            print(f"{len(before)} tables, {sum(before.values())} rows compared")
        finally:
            conn.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.migration_check")
    parser.add_argument("--db", required=True, help="the SQLite database to copy (never changed)")
    parser.add_argument("--since", type=int, default=29, help="roll back every step after this one (default 29: tonight's)")
    args = parser.parse_args(argv)
    source = Path(args.db)
    if not source.is_file():
        print(f"No database at {source}", file=sys.stderr)
        return 1
    problems = check(source, args.since)
    for p in problems:
        print(f"PROBLEM {p}", file=sys.stderr)
    print("migrations: ok" if not problems else "migrations: FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
