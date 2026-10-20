"""0014 (A1): `videos.made_with_brief`, the version of its project's brief
the video's last shipped edit was made with. NULL until something ships (a
video with nothing shipped was not made with any brief, so it is never
"Brief changed"); 0 means "made before this project's brief" (a video moved
in with edits already in it).

Backfill: a video in a project that has a brief, with at least one edit in
it, takes the version its last turn read (`settings.last_turn.brief_version`,
F2) or else the project's current version: what it was made with is not
known before this step, and calling every existing video stale would ask
for work nobody needs. Returns how many videos were set.
"""
from __future__ import annotations

import json

from app.store.migrations._util import add_column, drop_column


def _live_edits(conn, video_id: str) -> bool:
    for (body,) in conn.execute("SELECT body FROM edits WHERE project_id = ?", (video_id,)):
        if not json.loads(body or "{}").get("reverted"):
            return True
    return False


def up(conn) -> int:
    if not add_column(conn, "videos", "made_with_brief", "INTEGER"):
        return 0
    made = 0
    rows = conn.execute(
        "SELECT v.id, v.settings, p.brief_version FROM videos v JOIN projects p ON p.id = v.project_id "
        "WHERE p.brief_version IS NOT NULL").fetchall()
    for video_id, settings, current in rows:
        if not _live_edits(conn, video_id):
            continue
        read = (json.loads(settings or "{}").get("last_turn") or {}).get("brief_version")
        version = read if isinstance(read, int) and 0 < read <= current else current
        conn.execute("UPDATE videos SET made_with_brief = ? WHERE id = ?", (version, video_id))
        made += 1
    return made


def down(conn) -> None:
    drop_column(conn, "videos", "made_with_brief")
