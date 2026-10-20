"""A video's stage (F5): Draft, In review, Changes asked, Approved, Exported.
The stage changes only through `move`, which validates it and logs who,
when and why in the activity log (F7, verb `stage.moved`).

    current(db, video_id)                     -> stage | None (no such video)
    move(db, video_id, to, actor, why="")     -> StageMove | None (already there)
    history(db, video_id)                     -> [StageMove], newest first
    after_new_edit(db, video_id, actor)       -> StageMove | None

`after_new_edit` is the rule C1 calls when a new edit is added: an Approved
video goes back to Draft. Every move has a `move_in(c, ...)` form for a
transaction the caller holds.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from app.store import events
from app.store.actors import Actor
from app.store.db import Database
from app.timefmt import now_iso

STAGES = ("draft", "in_review", "changes_asked", "approved", "exported")
LABELS = {"draft": "Draft", "in_review": "In review", "changes_asked": "Changes asked",
          "approved": "Approved", "exported": "Exported"}


class StageError(ValueError):
    pass


@dataclass(frozen=True)
class StageMove:
    video_id: str
    from_stage: str
    to_stage: str
    actor_kind: str
    actor_name: str
    why: str
    at: str

    def to_dict(self) -> dict:
        return asdict(self)


def current_in(c: sqlite3.Connection, video_id: str) -> str | None:
    row = c.execute("SELECT stage FROM videos WHERE id = ?", (video_id,)).fetchone()
    return row[0] if row else None


def current(db: Database, video_id: str) -> str | None:
    with db.tx() as c:
        return current_in(c, video_id)


def move_in(c: sqlite3.Connection, video_id: str, to: str, actor: Actor, why: str = "") -> StageMove | None:
    """Move the video to stage `to`. None when it is there already;
    StageError for an unknown stage or video."""
    if to not in STAGES:
        raise StageError(f"A stage is one of: {', '.join(LABELS.values())}.")
    now = current_in(c, video_id)
    if now is None:
        raise StageError("No such video.")
    if now == to:
        return None
    move = StageMove(video_id, now, to, actor.kind, actor.name, " ".join(why.split())[:300], now_iso())
    c.execute("UPDATE videos SET stage = ? WHERE id = ?", (to, video_id))
    events.record(c, "stage.moved", actor, video_id=video_id, target=video_id,
                  payload={"from": move.from_stage, "to": to, "why": move.why})
    return move


def move(db: Database, video_id: str, to: str, actor: Actor, why: str = "") -> StageMove | None:
    with db.tx() as c:
        return move_in(c, video_id, to, actor, why)


def after_new_edit_in(c: sqlite3.Connection, video_id: str, actor: Actor) -> StageMove | None:
    """The rule (C1): a new edit on an Approved video moves it back to Draft."""
    if current_in(c, video_id) != "approved":
        return None
    return move_in(c, video_id, "draft", actor, "A new edit was added after approval.")


def after_new_edit(db: Database, video_id: str, actor: Actor) -> StageMove | None:
    with db.tx() as c:
        return after_new_edit_in(c, video_id, actor)


def history(db: Database, video_id: str) -> list[StageMove]:
    """Every move of the video, newest first."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM project_events WHERE video_id = ? AND verb = 'stage.moved' ORDER BY id DESC",
                         (video_id,)).fetchall()
    moves = []
    for r in rows:
        p = json.loads(r["payload"] or "{}")
        moves.append(StageMove(r["video_id"], p.get("from", ""), p.get("to", ""), r["actor_kind"], r["actor_name"],
                               p.get("why", ""), r["at"]))
    return moves
