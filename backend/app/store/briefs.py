"""Brief versions (F2): every save of a project's brief is a new version.

    current(db, project_id)        -> BriefVersion | None
    save(db, project_id, text, by) -> BriefVersion | None (None: no such project)
    history(db, project_id)        -> [BriefVersion], newest first
    diff(db, project_id, a, b)     -> [{"op": "same" | "added" | "removed", "text": ...}]

`save_in(c, ...)` is the same save on a transaction the caller holds, so a
change and its activity event (F7) land together. `projects.brief` is kept
equal to the current text: the read-only alias for one release. Each new
version writes a `brief.saved` event (F7).
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import asdict, dataclass

from app.store import events
from app.store.actors import user
from app.store.db import Database
from app.timefmt import now_iso


@dataclass(frozen=True)
class BriefVersion:
    project_id: str
    version: int
    text: str
    created_by: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _version(row) -> BriefVersion:
    return BriefVersion(row["project_id"], row["version"], row["text"], row["created_by"], row["created_at"])


def current_in(c: sqlite3.Connection, project_id: str) -> BriefVersion | None:
    row = c.execute(
        "SELECT b.* FROM project_briefs b JOIN projects p ON p.id = b.project_id AND p.brief_version = b.version "
        "WHERE b.project_id = ?", (project_id,)).fetchone()
    return _version(row) if row else None


def current(db: Database, project_id: str) -> BriefVersion | None:
    """The version the project points at; None before the first save."""
    with db.tx() as c:
        return current_in(c, project_id)


def save_in(c: sqlite3.Connection, project_id: str, text: str, by: str) -> BriefVersion | None:
    """A new version when the text changed; the current one when it did not
    (saving the same words twice is one version). None: no such project."""
    project = c.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        return None
    now = current_in(c, project_id)
    if now is not None and now.text == text:
        return now
    if now is None and not text.strip():
        c.execute("UPDATE projects SET brief = '' WHERE id = ?", (project_id,))   # still no brief: no version
        return None
    n = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM project_briefs WHERE project_id = ?", (project_id,)).fetchone()[0]
    c.execute("INSERT INTO project_briefs (project_id, version, text, created_by, created_at, workspace_id) "
              "VALUES (?, ?, ?, ?, ?, ?)", (project_id, n, text, by, now_iso(), project["workspace_id"]))
    c.execute("UPDATE projects SET brief = ?, brief_version = ? WHERE id = ?", (text, n, project_id))
    events.record(c, "brief.saved", user(by), project_id=project_id, target=f"v{n}", payload={"version": n})
    return current_in(c, project_id)


def save(db: Database, project_id: str, text: str, by: str) -> BriefVersion | None:
    with db.tx() as c:
        return save_in(c, project_id, text, by)


def history(db: Database, project_id: str) -> list[BriefVersion]:
    """Every version, newest first."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM project_briefs WHERE project_id = ? ORDER BY version DESC", (project_id,)).fetchall()
    return [_version(r) for r in rows]


def get(db: Database, project_id: str, version: int) -> BriefVersion | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_briefs WHERE project_id = ? AND version = ?", (project_id, version)).fetchone()
    return _version(row) if row else None


_TOKENS = re.compile(r"\s+|\S+")


def diff_text(old: str, new: str) -> list[dict]:
    """Word-level difference, whitespace kept with the words around it, as
    runs: [{"op": "same" | "added" | "removed", "text": ...}]."""
    a, b = _TOKENS.findall(old), _TOKENS.findall(new)
    out: list[dict] = []

    def put(op: str, text: str) -> None:
        if not text:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += text
        else:
            out.append({"op": op, "text": text})
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            put("same", "".join(a[i1:i2]))
        else:
            put("removed", "".join(a[i1:i2]))
            put("added", "".join(b[j1:j2]))
    return out


def diff(db: Database, project_id: str, a: int, b: int) -> list[dict] | None:
    """What changed from version `a` to version `b`; None if either is missing.
    Version 0 is the empty brief before the first save."""
    old = "" if a == 0 else getattr(get(db, project_id, a), "text", None)
    new = "" if b == 0 else getattr(get(db, project_id, b), "text", None)
    if old is None or new is None:
        return None
    return diff_text(old, new)
