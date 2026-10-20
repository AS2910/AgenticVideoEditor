"""0023 (D2): learned style.

    proposal_decisions   one row per decision on a line Voltage proposed:
                         added, rejected (discarded) or edited (rewritten
                         before adding), the words first voiced and the
                         words added, their word diff, the reason when given
    learned_items        what a pattern pass suggested (one line for the
                         brief or a style rule) and what became of it:
                         suggested, replaced, accepted, dismissed, removed

`down` drops both tables. An accepted item already lives in the brief or
the rules (their own tables), so dropping the list loses only the record of
where it came from, never the line itself."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS proposal_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT,
    project_id    TEXT,
    video_id      TEXT NOT NULL,
    plan_id       TEXT,
    item_id       TEXT,
    decision      TEXT NOT NULL,          -- added | rejected | edited
    reason        TEXT,
    proposed_text TEXT NOT NULL DEFAULT '',
    final_text    TEXT,
    diff          TEXT NOT NULL DEFAULT '[]',
    by            TEXT NOT NULL,
    at            TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS proposal_decisions_project ON proposal_decisions (project_id, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS learned_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT,
    project_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- brief | rule
    text          TEXT NOT NULL,
    why           TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,          -- suggested | replaced | accepted | dismissed | removed
    rule_id       INTEGER,
    brief_version INTEGER,
    at_count      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    decided_by    TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS learned_items_project ON learned_items (project_id, status)")


def down(conn) -> None:
    for table, index in (("learned_items", "learned_items_project"), ("proposal_decisions", "proposal_decisions_project")):
        if table in tables(conn):
            conn.execute(f"DROP INDEX IF EXISTS {index}")
            conn.execute(f"DROP TABLE {table}")
