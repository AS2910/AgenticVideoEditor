"""The one state a line is in (run 5 addendum 3).

Item 1 adds "needs_fix": a line the render carries but the check after the
render failed (`render.check`). It is never "in_your_video"; its row says
"Needs a fix" with the reason. Item 4 makes every surface read these states;
until then the row chip reads `needs_fix` from the render's `includes`.
"""
from __future__ import annotations

from typing import Iterable

ORIGINAL = "original"
PROPOSED = "proposed"
ADDED = "added"
RENDERING = "rendering"
IN_YOUR_VIDEO = "in_your_video"
NEEDS_FIX = "needs_fix"
LINE_STATES = (ORIGINAL, PROPOSED, ADDED, RENDERING, IN_YOUR_VIDEO, NEEDS_FIX)


def kept_line_state(ids: Iterable[str | None], video: dict | None, rendering: dict | None = None) -> tuple[str, str | None]:
    """(state, reason) for a kept line known by `ids` (its edit id, its
    candidate id), from the playing render's `includes` and the one rendering
    now. A line the playing render carries but failed the check needs a fix."""
    ids = [i for i in ids if i]

    def carries(inc: dict | None) -> bool:
        return bool(inc) and any(i in (inc.get("edit_ids") or ()) or i in (inc.get("candidate_ids") or ())
                                 or i in (inc.get("item_ids") or ()) for i in ids)

    if carries(video):
        needs = (video or {}).get("needs_fix") or {}
        reason = next((needs[i] for i in ids if i in needs), None)
        return (NEEDS_FIX, reason) if reason else (IN_YOUR_VIDEO, None)
    if carries(rendering):
        return RENDERING, None
    return ADDED, None
