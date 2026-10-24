"""Cost item 1d: paid reads of a clip kept by its content (migration 0038).

    get(db, owner, sha256, kind, key) -> dict | list | None
    put(db, owner, sha256, kind, key, body, video_id)
    forget(db, owner, sha256=None)  a deleted video's reads (or, with no sha256, all of an owner's)
    key_of(*parts) -> str          a short hash of what else a read depended on

A transcript, a look, an understanding or a reading of the same bytes, for
the same owner and the same inputs, is read once and reused: a re-upload
of a file never pays for it again.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.store.db import Database
from app.timefmt import now_iso


def key_of(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get(db: Database, owner: str, sha256: str | None, kind: str, key: str = "") -> Any:
    if not sha256:
        return None
    with db.tx() as c:
        row = c.execute("SELECT body FROM content_cache WHERE owner = ? AND sha256 = ? AND kind = ? AND key = ?",
                        (owner, sha256, kind, key)).fetchone()
    return json.loads(row["body"]) if row else None


def put(db: Database, owner: str, sha256: str | None, kind: str, key: str, body: Any, video_id: str | None = None) -> None:
    if not sha256 or body is None:
        return
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO content_cache (owner, sha256, kind, key, body, workspace_id, created_at) "
                  "VALUES (?, ?, ?, ?, ?, (SELECT workspace_id FROM videos WHERE id = ?), ?)",
                  (owner, sha256, kind, key, json.dumps(body, ensure_ascii=False), video_id, now_iso()))


def forget(db: Database, owner: str, sha256: str | None = None) -> None:
    with db.tx() as c:
        if sha256 is None:
            c.execute("DELETE FROM content_cache WHERE owner = ?", (owner,))
        else:
            c.execute("DELETE FROM content_cache WHERE owner = ? AND sha256 = ?", (owner, sha256))
