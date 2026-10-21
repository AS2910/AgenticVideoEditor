"""G8: thumbs up or down, with an optional reason, on a take or a turn.

    give(db, owner, video_id, target, target_id, vote, reason="")  -> dict (vote None clears it)
    for_video(db, owner, video_id) -> {"take": {id: {vote, reason}}, "turn": {...}}
    summary(db) -> totals per target and the newest, plus the newest error reports

A take is a proposal's candidate (`c12`), a turn is Voltage's reply (the
message's `seq`, as `m40`). One vote per person and target; the latest wins.
Each vote is also the analytics event `feedback.given` (G7)."""
from __future__ import annotations

import re

from app import analytics
from app.timefmt import now_iso

TARGETS = ("take", "turn")
VOTES = ("up", "down")
MAX_REASON = 500
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class FeedbackError(ValueError):
    """A vote that cannot be kept, with a sentence."""


def give(db, owner: str, video_id: str, target: str, target_id: str, vote: str | None, reason: str = "") -> dict:
    if target not in TARGETS:
        raise FeedbackError("Feedback goes on a take or a reply.")
    if not _ID.match(target_id or ""):
        raise FeedbackError("That take or reply is not one I know.")
    if vote is not None and vote not in VOTES:
        raise FeedbackError("A vote is up or down.")
    reason = " ".join((reason or "").split())[:MAX_REASON]
    with db.tx() as c:
        if vote is None:
            c.execute("DELETE FROM feedback WHERE owner = ? AND video_id = ? AND target = ? AND target_id = ?",
                      (owner, video_id, target, target_id))
            return {"target": target, "target_id": target_id, "vote": None, "reason": ""}
        row = c.execute("SELECT workspace_id FROM videos WHERE id = ?", (video_id,)).fetchone()
        c.execute("INSERT INTO feedback (workspace_id, owner, video_id, target, target_id, vote, reason, at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (owner, video_id, target, target_id) "
                  "DO UPDATE SET vote = excluded.vote, reason = excluded.reason, at = excluded.at",
                  (row[0] if row else None, owner, video_id, target, target_id, vote, reason, now_iso()))
        analytics.safe_in(c, "feedback.given", owner, {"target": target, "vote": vote, "reason": bool(reason),
                                                       "video_id": video_id})
    return {"target": target, "target_id": target_id, "vote": vote, "reason": reason}


def for_video(db, owner: str, video_id: str) -> dict:
    out: dict = {t: {} for t in TARGETS}
    with db.tx() as c:
        for r in c.execute("SELECT target, target_id, vote, reason FROM feedback WHERE owner = ? AND video_id = ?",
                           (owner, video_id)):
            out[r["target"]][r["target_id"]] = {"vote": r["vote"], "reason": r["reason"]}
    return out


def summary(db, limit: int = 20) -> dict:
    with db.tx() as c:
        totals = {t: {"target": t, "up": 0, "down": 0} for t in TARGETS}
        for r in c.execute("SELECT target, vote, COUNT(*) AS n FROM feedback GROUP BY target, vote"):
            if r["target"] in totals:
                totals[r["target"]][r["vote"]] = r["n"]
        recent = [{"target": r["target"], "video_id": r["video_id"], "target_id": r["target_id"], "vote": r["vote"],
                   "reason": r["reason"], "owner": r["owner"], "at": r["at"]}
                  for r in c.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,))]
        errors = int(c.execute("SELECT COUNT(*) FROM error_reports").fetchone()[0])
        latest = [{"message": r["message"], "source": r["source"], "at": r["at"], "where": r["location"]}
                  for r in c.execute("SELECT * FROM error_reports ORDER BY id DESC LIMIT 10")]
    return {"totals": list(totals.values()), "recent": recent, "errors": {"count": errors, "recent": latest}}
