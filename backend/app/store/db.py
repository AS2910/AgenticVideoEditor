"""The SQLite database behind projects, chat and spend (Phase 9).

One connection, shared across request and job-worker threads under a lock —
the write volume is a handful of rows per edit, so contention is not a
concern, and one connection keeps `:memory:` databases (tests) coherent.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- JSON
    transcript        TEXT NOT NULL,   -- JSON
    consent_at        TEXT,
    candidate_counter INTEGER NOT NULL DEFAULT 0,
    speakers          TEXT NOT NULL DEFAULT '{}'   -- JSON: label -> {name, voice_id}
);
CREATE INDEX IF NOT EXISTS projects_by_owner ON projects (owner, created_at);
CREATE TABLE IF NOT EXISTS candidates (
    project_id   TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    body         TEXT NOT NULL,        -- JSON
    PRIMARY KEY (project_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS edits (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- approval order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS messages (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    text       TEXT NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    vendor     TEXT NOT NULL,          -- "openai" | "elevenlabs" | "anthropic"
    what       TEXT NOT NULL,          -- e.g. "transcription", "speech", "intent"
    units      REAL NOT NULL,
    unit       TEXT NOT NULL,          -- "minutes" | "characters" | "tokens"
    usd        REAL NOT NULL,          -- estimated
    at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_by_project ON usage (project_id);
"""

PROJECT_TABLES = ("candidates", "edits", "messages", "usage")

# Columns added after a table first shipped: (table, column, definition).
# Applied to databases created before them; new databases get them from SCHEMA.
MIGRATIONS = (
    ("projects", "speakers", "TEXT NOT NULL DEFAULT '{}'"),   # Phase 11
)


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One transaction, exclusive to the calling thread."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def reset(self) -> None:
        """Empty every table. Intended for test isolation."""
        with self.tx() as c:
            for table in ("meta", "projects", *PROJECT_TABLES):
                c.execute(f"DELETE FROM {table}")
