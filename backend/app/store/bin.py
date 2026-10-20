"""The Bin (D3): what was deleted (F8) and is not purged yet, and putting
it back. Videos and projects carry `deleted_at`/`deleted_by`; a voice of
one's own is an entry in `meta` `my_voices:<owner>` carrying the same.

Restoring:
- a video goes back into its project, or becomes standalone when that
  project is in the Bin or gone (purged);
- a project comes back with the videos deleted with it (they share its
  `deleted_at`); a video deleted on its own before stays in the Bin;
- a voice comes back to the owner's voices.
Nothing made on an item was touched by deleting it, so its turns, edits
and renders come back as they were. Every restore is one F7 event in the
same transaction.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.store import events
from app.store.actors import Actor
from app.store.db import Database
from app.timefmt import now_iso

# How long an item waits in the Bin before the purge takes it (plan, open decision 7).
BIN_DAYS = 30


class NotInBin(LookupError):
    """No such item of the caller's in the Bin."""


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def days_left(deleted_at: str, now: datetime | None = None, days: int = BIN_DAYS) -> int:
    """Whole days until the purge may take it: 30 the day it was deleted, 0 when due."""
    now = now or datetime.now(timezone.utc)
    age = (now - _parse(deleted_at)).total_seconds() / 86400
    return max(0, days - int(age))


def items(db: Database, owner: str, now: datetime | None = None) -> list[dict]:
    """Everything of `owner`'s in the Bin, most recently deleted first."""
    out: list[dict] = []
    with db.tx() as c:
        projects = {r["id"]: r for r in c.execute("SELECT id, name, deleted_at FROM projects WHERE owner = ?", (owner,))}
        for r in c.execute("SELECT id, name, deleted_at, deleted_by FROM projects WHERE owner = ? AND deleted_at IS NOT NULL",
                           (owner,)):
            with_it = c.execute("SELECT COUNT(*) FROM videos WHERE project_id = ? AND deleted_at = ?",
                                (r["id"], r["deleted_at"])).fetchone()[0]
            out.append({"kind": "project", "id": r["id"], "name": r["name"], "deleted_at": r["deleted_at"],
                        "deleted_by": r["deleted_by"], "videos": with_it, "project_id": None, "project_name": None})
        for r in c.execute("SELECT id, source, project_id, deleted_at, deleted_by FROM videos "
                           "WHERE owner = ? AND deleted_at IS NOT NULL", (owner,)):
            project = projects.get(r["project_id"]) if r["project_id"] else None
            # A video that went with its project is restored with it; it still lists on its own.
            out.append({"kind": "video", "id": r["id"], "name": json.loads(r["source"] or "{}").get("filename") or r["id"],
                        "deleted_at": r["deleted_at"], "deleted_by": r["deleted_by"], "project_id": r["project_id"],
                        "project_name": project["name"] if project else None,
                        "project_in_bin": bool(project and project["deleted_at"]),
                        "with_project": bool(project and project["deleted_at"] == r["deleted_at"])})
        row = c.execute("SELECT value FROM meta WHERE key = ?", (f"my_voices:{owner}",)).fetchone()
        for v in json.loads(row[0]) if row else []:
            if v.get("deleted_at"):
                out.append({"kind": "voice", "id": v["voice_id"], "name": v.get("name") or v["voice_id"],
                            "deleted_at": v["deleted_at"], "deleted_by": v.get("deleted_by") or owner,
                            "project_id": None, "project_name": None,
                            "consent": bool(v.get("consent_granted_at"))})
    for item in out:
        item["days_left"] = days_left(item["deleted_at"], now)
    return sorted(out, key=lambda i: (i["deleted_at"], i["kind"], i["id"]), reverse=True)


def restore_video(db: Database, owner: str, video_id: str, by: str) -> dict:
    """Put a video back: into its project when that project is live, else
    standalone. Returns `{project_id, project_name, standalone_because}`."""
    with db.tx() as c:
        row = c.execute("SELECT project_id FROM videos WHERE id = ? AND owner = ? AND deleted_at IS NOT NULL",
                        (video_id, owner)).fetchone()
        if row is None:
            raise NotInBin(video_id)
        pid, because, name = row["project_id"], None, None
        if pid:
            project = c.execute("SELECT name, deleted_at FROM projects WHERE id = ?", (pid,)).fetchone()
            if project is None:
                pid, because = None, "Its project is gone, so it is a standalone video now."
            elif project["deleted_at"]:
                pid, because = None, f"Its project {project['name']} is in the Bin, so it is a standalone video now."
            else:
                name = project["name"]
        c.execute("UPDATE videos SET deleted_at = NULL, deleted_by = NULL, project_id = ? WHERE id = ?", (pid, video_id))
        events.record(c, "video.restored", Actor("user", by), video_id=video_id, project_id=pid, target=video_id,
                      payload={"standalone": pid is None and row["project_id"] is not None})
    return {"project_id": pid, "project_name": name, "standalone_because": because}


def restore_project(db: Database, owner: str, project_id: str, by: str) -> dict:
    """Put a project back with the videos that were deleted with it."""
    with db.tx() as c:
        row = c.execute("SELECT deleted_at FROM projects WHERE id = ? AND owner = ? AND deleted_at IS NOT NULL",
                        (project_id, owner)).fetchone()
        if row is None:
            raise NotInBin(project_id)
        videos = [r[0] for r in c.execute("SELECT id FROM videos WHERE project_id = ? AND deleted_at = ?",
                                          (project_id, row["deleted_at"]))]
        c.execute("UPDATE projects SET deleted_at = NULL, deleted_by = NULL WHERE id = ?", (project_id,))
        actor = Actor("user", by)
        for vid in videos:
            c.execute("UPDATE videos SET deleted_at = NULL, deleted_by = NULL WHERE id = ?", (vid,))
            events.record(c, "video.restored", actor, video_id=vid, project_id=project_id, target=vid,
                          payload={"with_project": True})
        events.record(c, "project.restored", actor, project_id=project_id, target=project_id,
                      payload={"videos": videos})
    return {"videos": videos}


def restore_voice(db: Database, owner: str, voice_id: str, by: str) -> dict:
    """Put one of the owner's voices back in their list."""
    key = f"my_voices:{owner}"
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        voices = json.loads(row[0]) if row else []
        found = next((v for v in voices if v["voice_id"] == voice_id and v.get("deleted_at")), None)
        if found is None:
            raise NotInBin(voice_id)
        found.pop("deleted_at", None)
        found.pop("deleted_by", None)
        found["restored_at"] = now_iso()
        c.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(voices), key))
        events.record(c, "voice.restored", Actor("user", by), target=voice_id, payload={"name": found.get("name")})
    return {"name": found.get("name")}
