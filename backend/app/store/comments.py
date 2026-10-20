"""Review comments (C2): what a reviewer said about a video, at a time in one
of its versions, and the thread under it.

    add_in(c, video_id=, author_name=, at_s=, text=, version=, share_id=, author_kind=) -> Comment
    get(db, comment_id) / for_video(db, video_id) / for_share(db, share_id, video_id=None)
    reply(db, comment_id, author_kind, author_name, text)  -> Comment
    set_status(db, comment_id, resolved, by)                -> Comment
    open_counts(db, video_ids)                              -> {video_id: open comments}

Writers take the caller's connection where an F7 event must land in the same
transaction (the API records `review.commented` and friends beside them).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from app.store.db import Database
from app.timefmt import now_iso

MAX_TEXT = 2000
MAX_NAME = 80


class CommentError(ValueError):
    """A comment or reply that cannot be kept, with a sentence to show."""


@dataclass(frozen=True)
class Comment:
    comment_id: int
    video_id: str
    project_id: str | None
    share_id: str | None
    author_kind: str
    author_name: str
    at_s: float
    version: int | None
    text: str
    status: str
    replies: list
    created_at: str
    resolved_at: str | None
    resolved_by: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _comment(row) -> Comment:
    return Comment(row["id"], row["video_id"], row["project_id"], row["share_id"], row["author_kind"], row["author_name"],
                   float(row["at_s"]), row["version"], row["text"], row["status"], json.loads(row["replies"] or "[]"),
                   row["created_at"], row["resolved_at"], row["resolved_by"])


def clean_text(text: str | None) -> str:
    said = (text or "").strip()
    if not said:
        raise CommentError("Write something first.")
    if len(said) > MAX_TEXT:
        raise CommentError(f"Keep it under {MAX_TEXT} characters.")
    return said


def clean_name(name: str | None) -> str | None:
    return " ".join((name or "").split())[:MAX_NAME] or None


def add_in(c: sqlite3.Connection, *, video_id: str, author_name: str, at_s: float, text: str,
           version: int | None = None, share_id: str | None = None, author_kind: str = "reviewer") -> Comment:
    said = clean_text(text)
    if at_s < 0:
        raise CommentError("A comment sits at a time in the video.")
    row = c.execute("SELECT project_id, workspace_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if row is None:
        raise CommentError("That video is not here any more.")
    c.execute("INSERT INTO review_comments (workspace_id, project_id, video_id, share_id, author_kind, author_name, at_s, "
              "version, text, status, replies, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', '[]', ?)",
              (row["workspace_id"], row["project_id"], video_id, share_id, author_kind,
               clean_name(author_name) or "A reviewer", round(float(at_s), 2), version, said, now_iso()))
    found = get_in(c, int(c.execute("SELECT last_insert_rowid()").fetchone()[0]))
    assert found is not None
    return found


def get_in(c: sqlite3.Connection, comment_id: int) -> Comment | None:
    row = c.execute("SELECT * FROM review_comments WHERE id = ?", (comment_id,)).fetchone()
    return _comment(row) if row else None


def get(db: Database, comment_id: int) -> Comment | None:
    with db.tx() as c:
        return get_in(c, comment_id)


def for_video(db: Database, video_id: str) -> list[Comment]:
    """Every comment on the video, in time order (then oldest first)."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM review_comments WHERE video_id = ? ORDER BY at_s, id", (video_id,)).fetchall()
    return [_comment(r) for r in rows]


def for_share(db: Database, share_id: str, video_id: str | None = None) -> list[Comment]:
    """The comments that came through one review link (what its reviewer sees)."""
    sql, args = "SELECT * FROM review_comments WHERE share_id = ?", [share_id]
    if video_id is not None:
        sql += " AND video_id = ?"
        args.append(video_id)
    with db.tx() as c:
        rows = c.execute(sql + " ORDER BY at_s, id", args).fetchall()
    return [_comment(r) for r in rows]


def count_for_share(db: Database, share_id: str) -> int:
    with db.tx() as c:
        return int(c.execute("SELECT COUNT(*) FROM review_comments WHERE share_id = ?", (share_id,)).fetchone()[0])


def reply_in(c: sqlite3.Connection, comment_id: int, author_kind: str, author_name: str, text: str) -> Comment:
    found = get_in(c, comment_id)
    if found is None:
        raise CommentError("That comment is not here any more.")
    replies = [*found.replies, {"author_kind": author_kind, "author_name": clean_name(author_name) or "",
                                "text": clean_text(text), "at": now_iso()}]
    c.execute("UPDATE review_comments SET replies = ? WHERE id = ?", (json.dumps(replies), comment_id))
    return get_in(c, comment_id)  # type: ignore[return-value]


def set_status_in(c: sqlite3.Connection, comment_id: int, resolved: bool, by: str) -> Comment:
    found = get_in(c, comment_id)
    if found is None:
        raise CommentError("That comment is not here any more.")
    if resolved:
        c.execute("UPDATE review_comments SET status = 'resolved', resolved_at = ?, resolved_by = ? WHERE id = ?",
                  (now_iso(), by, comment_id))
    else:
        c.execute("UPDATE review_comments SET status = 'open', resolved_at = NULL, resolved_by = NULL WHERE id = ?", (comment_id,))
    return get_in(c, comment_id)  # type: ignore[return-value]


def open_counts(db: Database, video_ids: list[str]) -> dict[str, int]:
    if not video_ids:
        return {}
    marks = ",".join("?" for _ in video_ids)
    with db.tx() as c:
        rows = c.execute(f"SELECT video_id, COUNT(*) FROM review_comments WHERE status = 'open' AND video_id IN ({marks}) "
                         "GROUP BY video_id", video_ids).fetchall()
    return {r[0]: int(r[1]) for r in rows}
