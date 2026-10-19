"""The SQLite database behind videos, projects (folders), chat and spend (Phase 9).

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
CREATE TABLE IF NOT EXISTS videos (
    id                TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- JSON
    transcript        TEXT NOT NULL,   -- JSON
    consent_at        TEXT,
    candidate_counter INTEGER NOT NULL DEFAULT 0,
    speakers          TEXT NOT NULL DEFAULT '{}',  -- JSON: label -> {name, voice_id}
    settings          TEXT NOT NULL DEFAULT '{}',  -- JSON: per-video preferences
    project_id        TEXT                         -- the folder it is in (Folders), NULL = standalone
);
CREATE INDEX IF NOT EXISTS videos_by_owner ON videos (owner, created_at);
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,                  -- f<n>
    owner       TEXT NOT NULL,
    name        TEXT NOT NULL,
    brief       TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',        -- JSON: defaults for new videos
    ceiling_usd REAL,
    created_at  TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS turns (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    content    TEXT NOT NULL,          -- JSON: the content blocks as the model saw them (Phase 20)
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS plans (
    project_id TEXT NOT NULL,
    plan_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- creation order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, plan_id)
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    vendor     TEXT NOT NULL,          -- "openai" | "elevenlabs" | "anthropic"
    what       TEXT NOT NULL,          -- e.g. "transcription", "speech", "intent"
    units      REAL NOT NULL,
    unit       TEXT NOT NULL,          -- "minutes" | "characters" | "tokens"
    usd        REAL NOT NULL,          -- estimated
    at         TEXT NOT NULL,
    folder_id  TEXT                    -- the video's project at the time of the charge (Folders)
);
CREATE INDEX IF NOT EXISTS usage_by_project ON usage (project_id);
"""

# The tables keyed by a video's id (their `project_id` column is the video id,
# from before projects were folders).
PROJECT_TABLES = ("candidates", "edits", "messages", "usage", "plans", "turns")

# Columns added after a table first shipped: (table, column, definition).
# Applied to databases created before them; new databases get them from SCHEMA.
MIGRATIONS = (
    ("videos", "speakers", "TEXT NOT NULL DEFAULT '{}'"),     # Phase 11
    ("videos", "settings", "TEXT NOT NULL DEFAULT '{}'"),     # Phase 12
    ("messages", "kind", "TEXT NOT NULL DEFAULT 'say'"),      # Phase 20: "say" | "step"
    ("messages", "cost", "REAL"),                             # Phase 20: what a step cost, in dollars
    ("messages", "data", "TEXT"),                             # Phase 20b: a card's facts (voice previews), JSON
    ("videos", "project_id", "TEXT"),                         # Folders: the folder a video is in
    ("usage", "folder_id", "TEXT"),                           # Folders: the folder at the time of the charge
)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _migrate_projects_to_videos(conn: sqlite3.Connection) -> bool:
    """Folders: the `projects` table of a database made before projects were
    folders holds videos. Renamed once, before the schema makes the new
    `projects` (folder) table; every row becomes a standalone video. True
    when the rename happened."""
    have = _tables(conn)
    if "videos" in have or "projects" not in have:
        return False
    conn.execute("ALTER TABLE projects RENAME TO videos")
    # The old index keeps its name across the rename; the schema makes the new one.
    conn.execute("DROP INDEX IF EXISTS projects_by_owner")
    return True


# Bug 2 (2026-10-19): every stored moment in one form, once. Plain columns,
# the JSON in settings, plans and meta; a voice's boolean consent becomes the
# moment it was given — the entry's own time, marked approximate — never 0.
TIME_COLUMNS = (("videos", "created_at"), ("videos", "consent_at"), ("projects", "created_at"),
                ("messages", "at"), ("turns", "at"), ("usage", "at"))
TIMES_DONE = "times_v2"


def _voice_consent(entry: dict) -> dict:
    out = {k: v for k, v in entry.items() if k != "consent"}
    if "consent_granted_at" in entry:
        return out
    given = entry.get("consent")
    kind = entry.get("kind") or "recorded"
    if given is False or (given is None and kind in ("designed", "library")):
        out["consent_granted_at"] = None
    else:
        # A recorded, cloned or shared-with-consent voice: the box was ticked when it was made.
        out["consent_granted_at"] = entry.get("at")
        out["consent_approximate"] = True
    return out


def _migrate_times(conn: sqlite3.Connection) -> int:
    """Rewrite every stored moment to the canonical form; returns how many changed."""
    import json
    from app.timefmt import normalise, to_iso
    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (TIMES_DONE,)).fetchone():
        return 0
    changed = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, column in TIME_COLUMNS:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                continue
            for row in conn.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}").fetchall():
                new = to_iso(row["v"])
                if new is None and column != "consent_at":
                    continue   # a NOT NULL time that does not parse is left as it is, never zeroed
                if new != row["v"]:
                    conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (new, row["rid"]))
                    changed += 1
        for table, column in (("videos", "settings"), ("plans", "body"), ("projects", "settings")):
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                continue
            for row in conn.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}").fetchall():
                try:
                    value = json.loads(row["v"] or "null")
                except ValueError:
                    continue
                new, n = normalise(value)
                if n:
                    conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (json.dumps(new), row["rid"]))
                    changed += n
        for row in conn.execute("SELECT key, value FROM meta").fetchall():
            try:
                value = json.loads(row["value"])
            except ValueError:
                continue
            if not isinstance(value, (dict, list)):
                continue
            new, n = normalise(value)
            if row["key"].startswith(("my_voices:", "project_voices:")) and isinstance(new, list):
                fixed = [_voice_consent(e) if isinstance(e, dict) else e for e in new]
                n += sum(1 for a, b in zip(new, fixed) if a != b)
                new = fixed
            if n:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(new), row["key"]))
                changed += n
        # A shared voice's consent is its owner's: the moment the voice was made, not the moment it was shared.
        owners: dict[str, str] = {}
        for row in conn.execute("SELECT value FROM meta WHERE key LIKE 'my_voices:%'").fetchall():
            for e in json.loads(row["value"] or "[]"):
                if isinstance(e, dict) and e.get("consent_granted_at"):
                    owners[e["voice_id"]] = e["consent_granted_at"]
        for row in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'project_voices:%'").fetchall():
            entries = json.loads(row["value"] or "[]")
            fixed = [{**e, "consent_granted_at": owners[e["voice_id"]]} if isinstance(e, dict) and e.get("consent_approximate") and e.get("voice_id") in owners else e for e in entries]
            if fixed != entries:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(fixed), row["key"]))
        from app.timefmt import now_iso
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (TIMES_DONE, now_iso()))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed


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
            # The chaos pass: another process on the same file (a second server,
            # a script) holds a write lock for a moment; wait up to 5 s rather
            # than failing the request with "database is locked".
            self._conn.execute("PRAGMA busy_timeout=5000")
            self.migrated_projects_to_videos = _migrate_projects_to_videos(self._conn)
            self._conn.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            self.migrated_times = _migrate_times(self._conn)

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
            for table in ("meta", "videos", "projects", *PROJECT_TABLES):
                c.execute(f"DELETE FROM {table}")
