"""Home's housekeeping (D4): pins, archived projects and search.

- **Pins** are per user (`pins(owner, kind, item_id)`): projects and videos
  pinned to the top of Home's sidebar, oldest pin first.
- **Archive** a project (`projects.archived_at/by`): hidden from Home, still
  searchable, read-only until unarchived. Every change to it or to a video
  in it is refused with `ARCHIVED` (the API checks `archived_project_of`).
- **Search** across project names, video names, what is said in each video
  (its transcript's words, with the time each hit starts) and brief text,
  grouped by project. Deleted items (F8) never show; archived ones do.
  An FTS5 trigram index (migration 0033, `search_fts`) narrows the rows
  read; the checks on them are the same as before it (9d).
"""
from __future__ import annotations

import json
import re
import sqlite3

from app.store import events
from app.store.actors import Actor
from app.store.db import Database
from app.store.workspaces import personal
from app.timefmt import now_iso

ARCHIVED = "This project is archived. Unarchive it to make changes."
KINDS = ("project", "video")
_WORD = re.compile(r"[\w']+", re.UNICODE)


class NotFound(LookupError):
    pass


# ── pins ──

def pins(db: Database, owner: str) -> list[dict]:
    """The owner's live pins, oldest first, with each item's name (a pin on
    something deleted is skipped, and comes back if it is restored)."""
    out = []
    with db.tx() as c:
        for r in c.execute("SELECT kind, item_id, pinned_at FROM pins WHERE owner = ? ORDER BY pinned_at, rowid", (owner,)):
            if r["kind"] == "project":
                row = c.execute("SELECT name, archived_at FROM projects WHERE id = ? AND owner = ? AND deleted_at IS NULL",
                                (r["item_id"], owner)).fetchone()
                if row:
                    out.append({"kind": "project", "id": r["item_id"], "name": row["name"], "pinned_at": r["pinned_at"],
                                "archived": bool(row["archived_at"])})
            else:
                row = c.execute("SELECT source, project_id FROM videos WHERE id = ? AND owner = ? AND deleted_at IS NULL",
                                (r["item_id"], owner)).fetchone()
                if row:
                    out.append({"kind": "video", "id": r["item_id"], "name": json.loads(row["source"] or "{}").get("filename") or r["item_id"],
                                "pinned_at": r["pinned_at"], "project_id": row["project_id"]})
    return out


def _owns(c: sqlite3.Connection, owner: str, kind: str, item_id: str) -> bool:
    table = "projects" if kind == "project" else "videos"
    return c.execute(f"SELECT 1 FROM {table} WHERE id = ? AND owner = ? AND deleted_at IS NULL", (item_id, owner)).fetchone() is not None


def pin(db: Database, owner: str, kind: str, item_id: str) -> bool:
    """Pin one of the owner's projects or videos. False when it was pinned already."""
    with db.tx() as c:
        if kind not in KINDS or not _owns(c, owner, kind, item_id):
            raise NotFound(item_id)
        added = c.execute("INSERT OR IGNORE INTO pins (owner, kind, item_id, pinned_at, workspace_id) VALUES (?, ?, ?, ?, ?)",
                          (owner, kind, item_id, now_iso(), personal(c, owner))).rowcount
    return added > 0


def unpin(db: Database, owner: str, kind: str, item_id: str) -> bool:
    """Unpin; NotFound for something the owner neither pinned nor owns (launch item 1)."""
    with db.tx() as c:
        gone = c.execute("DELETE FROM pins WHERE owner = ? AND kind = ? AND item_id = ?", (owner, kind, item_id)).rowcount > 0
        if not gone and (kind not in KINDS or not _owns(c, owner, kind, item_id)):
            raise NotFound(item_id)
        return gone


# ── archive ──

def set_archived(db: Database, project_id: str, by: str, archived: bool) -> bool:
    """Archive or unarchive a project; one F7 event. False when it already was."""
    with db.tx() as c:
        if archived:
            changed = c.execute("UPDATE projects SET archived_at = ?, archived_by = ? WHERE id = ? AND archived_at IS NULL",
                                (now_iso(), by, project_id)).rowcount
        else:
            changed = c.execute("UPDATE projects SET archived_at = NULL, archived_by = NULL WHERE id = ? AND archived_at IS NOT NULL",
                                (project_id,)).rowcount
        if changed:
            events.record(c, "project.archived" if archived else "project.unarchived", Actor("user", by),
                          project_id=project_id, target=project_id)
    return changed > 0


def archived_projects(db: Database, owner: str) -> set[str]:
    with db.tx() as c:
        return {r[0] for r in c.execute("SELECT id FROM projects WHERE owner = ? AND archived_at IS NOT NULL AND deleted_at IS NULL",
                                        (owner,))}


def archived_project_of(db: Database, *, video_id: str | None = None, project_id: str | None = None) -> dict | None:
    """The archived project a video is in (or the project named), as
    `{id, owner}`; None when it is not archived."""
    with db.tx() as c:
        if video_id is not None:
            row = c.execute("SELECT project_id FROM videos WHERE id = ?", (video_id,)).fetchone()
            project_id = row[0] if row else None
        if not project_id:
            return None
        row = c.execute("SELECT id, owner FROM projects WHERE id = ? AND archived_at IS NOT NULL", (project_id,)).fetchone()
    return {"id": row["id"], "owner": row["owner"]} if row else None


# ── search ──

def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


def _snippet(text: str, needle: str, width: int = 60) -> str:
    at = text.lower().find(needle.lower())
    if at < 0:
        return text[:width * 2].strip()
    start, end = max(0, at - width), min(len(text), at + len(needle) + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def transcript_hits(words: list[dict], query: str, limit: int = 3) -> list[dict]:
    """Where the query's words are said, in order, one after another (the
    last word may be the start of one): the time each hit starts and the
    words around it."""
    want = _tokens(query)
    if not want:
        return []
    said = [(_tokens(w.get("text", "")) or [""])[0] for w in words]
    hits = []
    for i in range(len(said) - len(want) + 1):
        if all(said[i + k] == want[k] for k in range(len(want) - 1)) and said[i + len(want) - 1].startswith(want[-1]):
            around = words[max(0, i - 4): i + len(want) + 6]
            hits.append({"at": float(words[i]["start"]), "text": " ".join(w.get("text", "").strip() for w in around).strip(),
                         "match": " ".join(w.get("text", "").strip() for w in words[i:i + len(want)])})
            if len(hits) >= limit:
                break
    return hits


def _phrase(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _candidates(db: Database, c: sqlite3.Connection, owner: str, q: str) -> dict[str, str | None]:
    """9d: the FTS5 MATCH expression that narrows each kind's rows, or None to
    read every row (as before the index). Always a superset of what `search`
    keeps: its own checks still decide. A project matches on the query as a
    substring of its name or brief; a video on that, or on every query word
    of 3+ letters as a substring of its words (a word under 3 letters cannot
    narrow a trigram index, so the video side reads every row then)."""
    if getattr(db, "dialect", "sqlite") != "sqlite":
        # TODO(postgres): the same narrowing over a `tsvector`/pg_trgm index
        # behind this function (projects: name || brief; videos: file name ||
        # transcript words), returning ids the exact checks below then run on.
        return {"project": None, "video": None}
    from app.store.migrations.m0033_search_fts import available
    if len(q) < 3 or not available(c):
        return {"project": None, "video": None}
    whole = _phrase(q.lower())
    long = [t for t in _tokens(q) if len(t) >= 3]
    return {"project": whole,
            "video": f"{whole} OR ({' AND '.join(_phrase(t) for t in long)})" if long else None}


def _narrowed(c: sqlite3.Connection, kind: str, owner: str, match: str | None) -> set[str] | None:
    if match is None:
        return None
    return {r[0] for r in c.execute("SELECT item_id FROM search_fts WHERE search_fts MATCH ? AND kind = ? AND owner = ?",
                                    (match, kind, owner))}


def search(db: Database, owner: str, query: str, limit: int = 40) -> dict:
    """Matches grouped by project (standalone videos last), each group's
    hits in order: the project's name, its brief, then per video its name
    and the moments it says the words."""
    q = (query or "").strip()
    if len(q) < 2:
        return {"query": q, "groups": [], "total": 0}
    ql = q.lower()
    groups: dict[str | None, dict] = {}
    total = 0

    def group(pid: str | None, name: str | None, archived: bool) -> dict:
        return groups.setdefault(pid, {"project_id": pid, "project_name": name or "Standalone videos",
                                       "archived": archived, "hits": []})

    with db.tx() as c:
        narrow = _candidates(db, c, owner, q)
        maybe_projects = _narrowed(c, "project", owner, narrow["project"])
        maybe_videos = _narrowed(c, "video", owner, narrow["video"])
        projects = {r["id"]: r for r in c.execute(
            "SELECT id, name, brief, archived_at FROM projects WHERE owner = ? AND deleted_at IS NULL", (owner,))}
        for pid, p in projects.items():
            if maybe_projects is not None and pid not in maybe_projects:
                continue
            if ql in (p["name"] or "").lower():
                group(pid, p["name"], bool(p["archived_at"]))["hits"].append({"kind": "project", "text": p["name"]})
            if ql in (p["brief"] or "").lower():
                group(pid, p["name"], bool(p["archived_at"]))["hits"].append({"kind": "brief", "text": _snippet(p["brief"], q)})
        videos = c.execute("SELECT id, source, transcript, project_id FROM videos WHERE owner = ? AND deleted_at IS NULL "
                           + ("" if maybe_videos is None else
                              "AND id IN (SELECT item_id FROM search_fts WHERE search_fts MATCH ? AND kind = 'video' AND owner = ?) ")
                           + "ORDER BY created_at DESC, id DESC",
                           (owner,) if maybe_videos is None else (owner, narrow["video"], owner)).fetchall()
    for v in videos:
        pid = v["project_id"] if v["project_id"] in projects else None
        p = projects.get(pid) if pid else None
        name = json.loads(v["source"] or "{}").get("filename") or v["id"]
        found = []
        if ql in name.lower():
            found.append({"kind": "video", "video_id": v["id"], "text": name})
        words = json.loads(v["transcript"] or "{}").get("words") or []
        found += [{"kind": "transcript", "video_id": v["id"], "filename": name, **h} for h in transcript_hits(words, q)]
        if found:
            for h in found:
                h.setdefault("filename", name)
            group(pid, p["name"] if p else None, bool(p and p["archived_at"]))["hits"].extend(found)
    ordered = [g for k, g in groups.items() if k is not None] + ([groups[None]] if None in groups else [])
    out = []
    for g in ordered:
        room = limit - total
        if room <= 0:
            break
        g["hits"] = g["hits"][:room]
        total += len(g["hits"])
        out.append(g)
    return {"query": q, "groups": out, "total": total}
