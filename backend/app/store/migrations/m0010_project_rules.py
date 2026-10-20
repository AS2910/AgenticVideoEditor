"""0010 (F3): the project's rules store. Kinds: `pronounce` (a term and how
to say it), `banned` (a word never said), `required_line` (a line every
video carries), `style` (a plain style rule). Every change bumps the row's
`version` and the project's `rules_version`, so a turn or a check can say
which rules it read."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS project_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,        -- f<n>
    kind         TEXT NOT NULL,        -- pronounce | banned | required_line | style
    data         TEXT NOT NULL,        -- JSON, by kind
    version      INTEGER NOT NULL,     -- 1, then +1 on every change to this rule
    created_by   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS project_rules_by_project ON project_rules (project_id, kind, id)")
    add_column(conn, "projects", "rules_version", "INTEGER NOT NULL DEFAULT 0")


def down(conn) -> None:
    drop_column(conn, "projects", "rules_version")
    if "project_rules" in tables(conn):
        conn.execute("DROP INDEX IF EXISTS project_rules_by_project")
        conn.execute("DROP TABLE project_rules")
