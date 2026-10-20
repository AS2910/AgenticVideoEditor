"""0012 (F7): the activity log. One row per thing that happened to a
project or a video: who (user, Voltage, reviewer), the verb, its target and
the facts as JSON. Written in the same transaction as the change.

The stage moves 0011 kept in `stage_log` move in here (verb `stage.moved`)
and `stage_log` goes; `down` puts them back."""
from __future__ import annotations

import json

from app.store.migrations._util import tables

COPY_DOWN = """CREATE TABLE IF NOT EXISTS stage_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     TEXT NOT NULL,
    from_stage   TEXT NOT NULL,
    to_stage     TEXT NOT NULL,
    actor_kind   TEXT NOT NULL,        -- user | voltage | reviewer
    actor_name   TEXT NOT NULL,
    why          TEXT NOT NULL,
    at           TEXT NOT NULL,
    workspace_id TEXT
)"""


def up(conn) -> int:
    conn.execute("""CREATE TABLE IF NOT EXISTS project_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    project_id   TEXT,                 -- f<n>, or NULL for a standalone video's event
    video_id     TEXT,                 -- p<n>, or NULL for a project's own event
    actor_kind   TEXT NOT NULL,        -- user | voltage | reviewer
    actor_name   TEXT NOT NULL,
    verb         TEXT NOT NULL,        -- e.g. brief.saved, stage.moved, edit.shipped
    target       TEXT NOT NULL,        -- what it was done to, e.g. "v3", "e2", "p4"
    payload      TEXT NOT NULL,        -- JSON
    at           TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS project_events_by_project ON project_events (project_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS project_events_by_video ON project_events (video_id, id)")
    moved = 0
    if "stage_log" in tables(conn):
        for r in conn.execute("SELECT s.*, v.project_id AS folder FROM stage_log s LEFT JOIN videos v ON v.id = s.video_id ORDER BY s.id").fetchall():
            conn.execute(
                "INSERT INTO project_events (workspace_id, project_id, video_id, actor_kind, actor_name, verb, target, payload, at) "
                "VALUES (?, ?, ?, ?, ?, 'stage.moved', ?, ?, ?)",
                (r["workspace_id"], r["folder"], r["video_id"], r["actor_kind"], r["actor_name"], r["video_id"],
                 json.dumps({"from": r["from_stage"], "to": r["to_stage"], "why": r["why"]}), r["at"]))
            moved += 1
        conn.execute("DROP INDEX IF EXISTS stage_log_by_video")
        conn.execute("DROP TABLE stage_log")
    return moved


def down(conn) -> None:
    conn.execute(COPY_DOWN)
    conn.execute("CREATE INDEX IF NOT EXISTS stage_log_by_video ON stage_log (video_id, id)")
    if "project_events" not in tables(conn):
        return
    for r in conn.execute("SELECT * FROM project_events WHERE verb = 'stage.moved' ORDER BY id").fetchall():
        p = json.loads(r["payload"] or "{}")
        conn.execute("INSERT INTO stage_log (video_id, from_stage, to_stage, actor_kind, actor_name, why, at, workspace_id) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (r["video_id"], p.get("from", ""), p.get("to", ""), r["actor_kind"], r["actor_name"], p.get("why", ""),
                      r["at"], r["workspace_id"]))
    conn.execute("DROP INDEX IF EXISTS project_events_by_project")
    conn.execute("DROP INDEX IF EXISTS project_events_by_video")
    conn.execute("DROP TABLE project_events")
