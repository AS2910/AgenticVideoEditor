"""0022 (D1): project templates.

    project_templates   one row per template a user saved from a project:
                        its name and `data` (JSON: brief text, rules,
                        export presets, defaults, ceiling, voice entries),
                        the project it came from, who and when

The three starter templates are written in code (app/store/templates.py),
not rows, so they are the same for everyone and never deleted. `down` drops
the table: templates are a convenience and no project depends on one (a
project made from a template holds its own copy of everything)."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS project_templates (
    id                TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    workspace_id      TEXT,
    name              TEXT NOT NULL,
    data              TEXT NOT NULL DEFAULT '{}',
    source_project_id TEXT,
    created_by        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS project_templates_owner ON project_templates (owner, created_at)")


def down(conn) -> None:
    if "project_templates" in tables(conn):
        conn.execute("DROP INDEX IF EXISTS project_templates_owner")
        conn.execute("DROP TABLE project_templates")
