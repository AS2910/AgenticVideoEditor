"""The activity log (F7): who did what to a project or a video, and when.
It drives the project feed and, later, notifications.

    record(c, verb, actor, video_id=..., project_id=..., target=..., payload=...) -> id
    for_project(db, project_id, limit=50, before=None) -> {"events": [...], "next": id | None}
    for_video(db, video_id, limit=50, before=None)     -> the same, for one video

`record` takes the caller's connection: it is written in the same
transaction as the change it describes, so a change never lands without its
event or an event without its change. Lists are newest first; `next` is the
`before` to pass for the page after.
"""
from __future__ import annotations

import json
import sqlite3

from app.store.actors import Actor
from app.store.db import Database
from app.timefmt import now_iso

# The verbs written so far (more join as features land).
VERBS = ("brief.saved", "rule.added", "rule.changed", "rule.removed", "stage.moved",
         "video.moved_in", "video.moved_out", "edit.shipped", "edit.undone",
         "video.deleted", "video.restored", "project.deleted", "project.restored",
         # A1: bringing videos up to date with a changed brief.
         "brief.update_started", "brief.video_current", "brief.update_finished",
         # B2: language versions made from a master, and a version brought back in step.
         "language.versions_made", "language.sync_started", "language.synced",
         # C2: a review link's comments and answers (the reviewer as actor), the owner's replies.
         "review.commented", "review.approved", "review.changes_asked", "review.replied",
         "review.resolved", "review.reopened",
         # D1: templates saved, renamed, deleted, and a project made from one.
         "template.saved", "template.renamed", "template.deleted", "project.from_template",
         # D2: what a learned-style pass suggested, and what the user did with it.
         "learned.suggested", "learned.accepted", "learned.dismissed", "learned.removed")
MAX_PAGE = 200


def record(c: sqlite3.Connection, verb: str, actor: Actor, *, video_id: str | None = None,
           project_id: str | None = None, target: str = "", payload: dict | None = None,
           workspace_id: str | None = None) -> int:
    """Write one event inside the caller's transaction. A video's event takes
    the video's project when none is named; the workspace comes from the
    video, else the project."""
    if video_id and project_id is None:
        row = c.execute("SELECT project_id FROM videos WHERE id = ?", (video_id,)).fetchone()
        project_id = row[0] if row else None
    if workspace_id is None:
        row = c.execute("SELECT COALESCE((SELECT workspace_id FROM videos WHERE id = ?), "
                        "(SELECT workspace_id FROM projects WHERE id = ?))", (video_id or "", project_id or "")).fetchone()
        workspace_id = row[0] if row else None
    c.execute(
        "INSERT INTO project_events (workspace_id, project_id, video_id, actor_kind, actor_name, verb, target, payload, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (workspace_id, project_id, video_id, actor.kind, actor.name, verb, target,
         json.dumps(payload or {}), now_iso()))
    event_id = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    _mirror(c, verb, actor, video_id, project_id, workspace_id, payload or {})
    return event_id


def _mirror(c: sqlite3.Connection, verb: str, actor: Actor, video_id: str | None, project_id: str | None,
            workspace_id: str | None, payload: dict) -> None:
    """G7: every verb is also an analytics event for the workspace's owner, in
    the same transaction; an edit shipped is also a take added (the funnel)."""
    from app import analytics
    row = c.execute("SELECT owner FROM workspaces WHERE id = ?", (workspace_id or "",)).fetchone() if workspace_id else None
    owner = row[0] if row else (actor.name if actor.kind == "user" else None)
    if not owner:
        return
    props = {"video_id": video_id, "project_id": project_id, "actor": actor.kind,
             **{k: v for k, v in payload.items() if isinstance(v, (int, float, bool)) or k in ("why", "role", "kind", "to", "stage")}}
    analytics.safe_in(c, verb, owner, props, workspace_id=workspace_id)
    if verb == "edit.shipped":
        analytics.safe_in(c, "take_added", owner, {"video_id": video_id, "overridden": bool(payload.get("overridden"))},
                          workspace_id=workspace_id)


def _event(row) -> dict:
    return {"id": row["id"], "workspace_id": row["workspace_id"], "project_id": row["project_id"],
            "video_id": row["video_id"], "actor_kind": row["actor_kind"], "actor_name": row["actor_name"],
            "verb": row["verb"], "target": row["target"], "payload": json.loads(row["payload"] or "{}"), "at": row["at"]}


def _page(db: Database, column: str, value: str, limit: int, before: int | None) -> dict:
    limit = max(1, min(int(limit), MAX_PAGE))
    with db.tx() as c:
        rows = c.execute(
            f"SELECT * FROM project_events WHERE {column} = ?" + (" AND id < ?" if before else "")
            + " ORDER BY id DESC LIMIT ?", (value, *((before,) if before else ()), limit + 1)).fetchall()
    events = [_event(r) for r in rows[:limit]]
    return {"events": events, "next": events[-1]["id"] if len(rows) > limit else None}


def for_project(db: Database, project_id: str, limit: int = 50, before: int | None = None) -> dict:
    """The project's events (its own and its videos'), newest first."""
    return _page(db, "project_id", project_id, limit, before)


def for_video(db: Database, video_id: str, limit: int = 50, before: int | None = None) -> dict:
    return _page(db, "video_id", video_id, limit, before)
