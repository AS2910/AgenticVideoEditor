"""0001: the schema as it stood before the runner, minus the columns added
later (0002 to 0005 add those back). A database made before the runner
already has every table, so this changes nothing there.

Also the Folders rename: a database made before projects were folders holds
its videos in `projects`; that table becomes `videos` before the new
`projects` (folder) table is made. Returns True when the rename happened.
"""
from __future__ import annotations

import sqlite3

from app.store.migrations._util import tables

TABLES = {
    "meta": """CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)""",
    "videos": """CREATE TABLE IF NOT EXISTS videos (
    id                TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- JSON
    transcript        TEXT NOT NULL,   -- JSON
    consent_at        TEXT,
    candidate_counter INTEGER NOT NULL DEFAULT 0
)""",
    "projects": """CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,                  -- f<n>
    owner       TEXT NOT NULL,
    name        TEXT NOT NULL,
    brief       TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',        -- JSON: defaults for new videos
    ceiling_usd REAL,
    created_at  TEXT NOT NULL
)""",
    "candidates": """CREATE TABLE IF NOT EXISTS candidates (
    project_id   TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    body         TEXT NOT NULL,        -- JSON
    PRIMARY KEY (project_id, candidate_id)
)""",
    "edits": """CREATE TABLE IF NOT EXISTS edits (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- approval order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, seq)
)""",
    "messages": """CREATE TABLE IF NOT EXISTS messages (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    text       TEXT NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
)""",
    "turns": """CREATE TABLE IF NOT EXISTS turns (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    content    TEXT NOT NULL,          -- JSON: the content blocks as the model saw them (Phase 20)
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
)""",
    "plans": """CREATE TABLE IF NOT EXISTS plans (
    project_id TEXT NOT NULL,
    plan_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- creation order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, plan_id)
)""",
    "usage": """CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    vendor     TEXT NOT NULL,          -- "openai" | "elevenlabs" | "anthropic"
    what       TEXT NOT NULL,          -- e.g. "transcription", "speech", "intent"
    units      REAL NOT NULL,
    unit       TEXT NOT NULL,          -- "minutes" | "characters" | "tokens"
    usd        REAL NOT NULL,          -- estimated
    at         TEXT NOT NULL
)""",
    "jobs": """CREATE TABLE IF NOT EXISTS jobs (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL UNIQUE,   -- J<seq>
    project_id TEXT NOT NULL,          -- the video
    turn_id    TEXT,
    kind       TEXT NOT NULL,          -- voice_line | design_voice | clone | mix | render_preview | export
    status     TEXT NOT NULL,          -- queued | running | done | failed | cancelled
    touched    REAL NOT NULL,          -- epoch seconds of the last change, for the timeout sweep
    body       TEXT NOT NULL           -- JSON: the whole record (2026-10-20, one processing model)
)""",
}

INDEXES = (
    "CREATE INDEX IF NOT EXISTS videos_by_owner ON videos (owner, created_at)",
    "CREATE INDEX IF NOT EXISTS projects_by_owner ON projects (owner, created_at)",
    "CREATE INDEX IF NOT EXISTS usage_by_project ON usage (project_id)",
    "CREATE INDEX IF NOT EXISTS jobs_by_video ON jobs (project_id, seq)",
    "CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (status)",
)


def _rename_projects_to_videos(conn: sqlite3.Connection) -> bool:
    have = tables(conn)
    if "videos" in have or "projects" not in have:
        return False
    conn.execute("ALTER TABLE projects RENAME TO videos")
    # The old index keeps its name across the rename; the index list makes the new one.
    conn.execute("DROP INDEX IF EXISTS projects_by_owner")
    return True


def up(conn: sqlite3.Connection) -> bool:
    renamed = _rename_projects_to_videos(conn)
    for statement in TABLES.values():
        conn.execute(statement)
    for statement in INDEXES:
        conn.execute(statement)
    return renamed


def down(conn: sqlite3.Connection) -> None:
    """Drops the tables, but only when every one is empty: rolling the
    baseline back never deletes anyone's data."""
    have = tables(conn)
    # A later step's own marker in meta (0006's `times_v2`) is not anyone's data.
    markers = {"meta": " WHERE key NOT IN ('times_v2')"}
    full = [t for t in TABLES if t in have and conn.execute(f"SELECT 1 FROM {t}{markers.get(t, '')} LIMIT 1").fetchone()]
    if full:
        raise RuntimeError(f"refusing to drop the baseline: these tables hold rows: {', '.join(full)}")
    for table in reversed(list(TABLES)):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
