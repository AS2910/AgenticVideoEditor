"""0015 (A2): the project check. `project_checks` is one run (rules only or
with the Claude text pass, its job, what it cost, what it could not check);
`project_issues` the issues a run found, each with the videos and times it
names and the fingerprint of the text it was found in;
`project_issue_ignores` the fingerprints the user ignored, so an issue stays
ignored until the text it was found in changes."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS project_checks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,        -- f<n>
    mode         TEXT NOT NULL,        -- rules | full (rules plus the Claude text pass)
    status       TEXT NOT NULL,        -- running | done | failed
    job_id       TEXT,                 -- the Activity job (kind "check")
    trigger      TEXT NOT NULL,        -- user | brief (auto-run after a brief change) | preflight
    cost_usd     REAL NOT NULL DEFAULT 0,
    notes        TEXT NOT NULL DEFAULT '[]',   -- JSON: sentences about what was not checked
    error        TEXT,
    created_by   TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS project_checks_by_project ON project_checks (project_id, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS project_issues (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id     INTEGER NOT NULL,
    project_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,        -- fact | offer | voice | pronounce | banned | required_line | loudness
    message      TEXT NOT NULL,
    places       TEXT NOT NULL,        -- JSON: [{video_id, filename, t, text}]
    fingerprint  TEXT NOT NULL,        -- the issue's kind and key with the text it was found in, hashed
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS project_issues_by_check ON project_issues (check_id, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS project_issue_ignores (
    project_id   TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    ignored_by   TEXT NOT NULL,
    ignored_at   TEXT NOT NULL,
    workspace_id TEXT,
    PRIMARY KEY (project_id, fingerprint)
)""")


def down(conn) -> None:
    have = tables(conn)
    for index in ("project_checks_by_project", "project_issues_by_check"):
        conn.execute(f"DROP INDEX IF EXISTS {index}")
    for table in ("project_issue_ignores", "project_issues", "project_checks"):
        if table in have:
            conn.execute(f"DROP TABLE {table}")
