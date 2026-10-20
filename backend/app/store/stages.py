"""A video's stage (F5): Draft, In review, Changes asked, Approved, Exported.
The stage changes only through `move`, which validates it and logs who,
when and why in the activity log (F7, verb `stage.moved`).

    current(db, video_id)                     -> stage | None (no such video)
    move(db, video_id, to, actor, why="")     -> StageMove | None (already there)
    history(db, video_id)                     -> [StageMove], newest first
    after_new_edit(db, video_id, actor)       -> StageMove | None
    review_sent(db, video_ids, actor)         -> [StageMove]
    reviewer_approved(db, video_id, name)     -> StageMove | None
    reviewer_asked_changes(db, video_id, name)-> StageMove | None

The automatic moves (C1): a new edit on an Approved video takes it back to
Draft (`after_new_edit`, called where every edit is written, so every ship
path follows it); sending a review link puts a video In review; a reviewer's
approval makes it Approved, a change request Changes asked (C2 calls those
two). Everything else is a manual move. Every move has a `*_in(c, ...)` form
for a transaction the caller holds.
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


# What the editor and the project page say before an edit lands on an Approved video (C1).
APPROVED_WARNING = "This video is Approved. Adding this moves it back to Draft."


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


def review_sent_in(c: sqlite3.Connection, video_ids: list[str], actor: Actor,
                   why: str = "A review link was sent.") -> list[StageMove]:
    """Sending a review link puts each video In review (one already there stays)."""
    moves = [move_in(c, v, "in_review", actor, why) for v in video_ids if current_in(c, v) is not None]
    return [m for m in moves if m]


def review_sent(db: Database, video_ids: list[str], actor: Actor, why: str = "A review link was sent.") -> list[StageMove]:
    with db.tx() as c:
        return review_sent_in(c, video_ids, actor, why)


def reviewer_approved_in(c: sqlite3.Connection, video_id: str, name: str, version: int | None = None) -> StageMove | None:
    """A reviewer approved the video (C2): Approved, logged under their name."""
    why = f"Approved v{version} by review link." if version else "Approved by review link."
    return move_in(c, video_id, "approved", Actor("reviewer", name or "A reviewer"), why)


def reviewer_approved(db: Database, video_id: str, name: str, version: int | None = None) -> StageMove | None:
    with db.tx() as c:
        return reviewer_approved_in(c, video_id, name, version)


def reviewer_asked_changes_in(c: sqlite3.Connection, video_id: str, name: str, why: str = "") -> StageMove | None:
    """A reviewer asked for changes (C2): Changes asked, logged under their name."""
    return move_in(c, video_id, "changes_asked", Actor("reviewer", name or "A reviewer"), why or "Changes asked by review link.")


def reviewer_asked_changes(db: Database, video_id: str, name: str, why: str = "") -> StageMove | None:
    with db.tx() as c:
        return reviewer_asked_changes_in(c, video_id, name, why)


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
