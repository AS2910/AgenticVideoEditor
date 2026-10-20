"""0009 (F2): brief versions. Every save of a project's brief is a new row in
`project_briefs`; `projects.brief_version` points at the current one.
`projects.brief` stays, kept equal to the current version's text, as a
read-only alias for one release.

Backfill: a project with a brief gets it as version 1 (by its owner, at the
project's creation time); a project with no brief has no version yet.
Returns how many versions were made.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables


def up(conn) -> int:
    conn.execute("""CREATE TABLE IF NOT EXISTS project_briefs (
    project_id   TEXT NOT NULL,        -- f<n>
    version      INTEGER NOT NULL,     -- 1, 2, ... per project
    text         TEXT NOT NULL,
    created_by   TEXT NOT NULL,        -- the owner who saved it
    created_at   TEXT NOT NULL,
    workspace_id TEXT,
    PRIMARY KEY (project_id, version)
)""")
    add_column(conn, "projects", "brief_version", "INTEGER")
    made = 0
    rows = conn.execute(
        "SELECT id, owner, brief, created_at, workspace_id FROM projects "
        "WHERE brief_version IS NULL AND TRIM(COALESCE(brief, '')) != ''").fetchall()
    for r in rows:
        if conn.execute("SELECT 1 FROM project_briefs WHERE project_id = ?", (r[0],)).fetchone():
            continue
        conn.execute("INSERT INTO project_briefs (project_id, version, text, created_by, created_at, workspace_id) "
                     "VALUES (?, 1, ?, ?, ?, ?)", (r[0], r[2], r[1], r[3], r[4]))
        conn.execute("UPDATE projects SET brief_version = 1 WHERE id = ?", (r[0],))
        made += 1
    return made


def down(conn) -> None:
    # projects.brief always holds the current text, so nothing the user sees is lost; the history goes.
    drop_column(conn, "projects", "brief_version")
    if "project_briefs" in tables(conn):
        conn.execute("DROP TABLE project_briefs")
