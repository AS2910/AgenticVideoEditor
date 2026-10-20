"""Language sets (B2): a master video and its language versions.

A language version is a variant of its master (the same clip), linked by
`videos.master_id`, with its `language`. Keeping in step reads the activity
log (F7): the master's edit marker is the id of its newest `edit.shipped` or
`edit.undone` event, so every way a master's line changes (the editor, a
batch's Add all, Voltage) moves it with no other hook. A child made or last
synced at marker N is out of sync when the master's marker is past N, and
the changed lines are the master's edit events after N.

    LANGUAGES / label(code) / guess(text)
    marker(db, master_id)                     -> int
    changes_since(db, master_id, since)       -> [{edit_id, verb, event_id}] (net, in order)
"""
from __future__ import annotations

import re

from app.store.db import Database

# Decision 4 of the plan: Hindi, Hinglish, Tamil, Marathi, English.
LANGUAGES = {"hi": "Hindi", "hinglish": "Hinglish", "ta": "Tamil", "mr": "Marathi", "en": "English"}
EDIT_VERBS = ("edit.shipped", "edit.undone")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_TAMIL = re.compile(r"[஀-௿]")


def label(code: str | None) -> str | None:
    return LANGUAGES.get(code or "") if code else None


def guess(text: str) -> str:
    """The master's own language, from its script: Tamil or Devanagari
    letters say so (Devanagari is read as Hindi; Marathi shares the script),
    anything else is English. Hinglish in Latin letters reads as English."""
    if _TAMIL.search(text):
        return "ta"
    if _DEVANAGARI.search(text):
        return "hi"
    return "en"


def marker(db: Database, master_id: str) -> int:
    with db.tx() as c:
        row = c.execute("SELECT MAX(id) FROM project_events WHERE video_id = ? AND verb IN (?, ?)",
                        (master_id, *EDIT_VERBS)).fetchone()
    return int(row[0] or 0)


def changes_since(db: Database, master_id: str, since: int) -> list[dict]:
    """The master's edits shipped or undone after marker `since`, oldest
    first, one entry per edit with its last verb. An edit shipped and undone
    again since then changed nothing and is left out."""
    with db.tx() as c:
        rows = c.execute("SELECT id, verb, target FROM project_events WHERE video_id = ? AND verb IN (?, ?) "
                         "AND id > ? ORDER BY id", (master_id, *EDIT_VERBS, int(since or 0))).fetchall()
    first: dict[str, str] = {}
    last: dict[str, dict] = {}
    for r in rows:
        first.setdefault(r["target"], r["verb"])
        last[r["target"]] = {"edit_id": r["target"], "verb": r["verb"], "event_id": int(r["id"])}
    out = [e for t, e in last.items() if not (first[t] == "edit.shipped" and e["verb"] == "edit.undone")]
    return sorted(out, key=lambda e: e["event_id"])
