"""0006: Bug 2 (2026-10-19), one form for every stored moment (a data
migration). Guarded by the `times_v2` meta marker as before, so a database
that already ran it changes nothing. Returns how many values changed.

Down is a no-op that keeps the marker: the rewrite is one-way, the canonical
form it leaves is what every reader already accepts, and keeping the marker
means an up after a down never rewrites rows written since.
"""
from __future__ import annotations

import sqlite3

# Every stored moment in one form, once. Plain columns,
# the JSON in settings, plans and meta; a voice's boolean consent becomes the
# moment it was given — the entry's own time, marked approximate — never 0.
TIME_COLUMNS = (("videos", "created_at"), ("videos", "consent_at"), ("projects", "created_at"),
                ("messages", "at"), ("turns", "at"), ("usage", "at"))
TIMES_DONE = "times_v2"


def _voice_consent(entry: dict) -> dict:
    out = {k: v for k, v in entry.items() if k != "consent"}
    if "consent_granted_at" in entry:
        return out
    given = entry.get("consent")
    kind = entry.get("kind") or "recorded"
    if given is False or (given is None and kind in ("designed", "library")):
        out["consent_granted_at"] = None
    else:
        # A recorded, cloned or shared-with-consent voice: the box was ticked when it was made.
        out["consent_granted_at"] = entry.get("at")
        out["consent_approximate"] = True
    return out


def up(conn: sqlite3.Connection) -> int:
    """Rewrite every stored moment to the canonical form; returns how many changed."""
    import json
    from app.timefmt import normalise, to_iso
    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (TIMES_DONE,)).fetchone():
        return 0
    changed = 0
    for table, column in TIME_COLUMNS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            continue
        for row in conn.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}").fetchall():
            new = to_iso(row["v"])
            if new is None and column != "consent_at":
                continue   # a NOT NULL time that does not parse is left as it is, never zeroed
            if new != row["v"]:
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (new, row["rid"]))
                changed += 1
    for table, column in (("videos", "settings"), ("plans", "body"), ("projects", "settings")):
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            continue
        for row in conn.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}").fetchall():
            try:
                value = json.loads(row["v"] or "null")
            except ValueError:
                continue
            new, n = normalise(value)
            if n:
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (json.dumps(new), row["rid"]))
                changed += n
    for row in conn.execute("SELECT key, value FROM meta").fetchall():
        try:
            value = json.loads(row["value"])
        except ValueError:
            continue
        if not isinstance(value, (dict, list)):
            continue
        new, n = normalise(value)
        if row["key"].startswith(("my_voices:", "project_voices:")) and isinstance(new, list):
            fixed = [_voice_consent(e) if isinstance(e, dict) else e for e in new]
            n += sum(1 for a, b in zip(new, fixed) if a != b)
            new = fixed
        if n:
            conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(new), row["key"]))
            changed += n
    # A shared voice's consent is its owner's: the moment the voice was made, not the moment it was shared.
    owners: dict[str, str] = {}
    for row in conn.execute("SELECT value FROM meta WHERE key LIKE 'my_voices:%'").fetchall():
        for e in json.loads(row["value"] or "[]"):
            if isinstance(e, dict) and e.get("consent_granted_at"):
                owners[e["voice_id"]] = e["consent_granted_at"]
    for row in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'project_voices:%'").fetchall():
        entries = json.loads(row["value"] or "[]")
        fixed = [{**e, "consent_granted_at": owners[e["voice_id"]]} if isinstance(e, dict) and e.get("consent_approximate") and e.get("voice_id") in owners else e for e in entries]
        if fixed != entries:
            conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(fixed), row["key"]))
    from app.timefmt import now_iso
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (TIMES_DONE, now_iso()))
    return changed


def down(conn: sqlite3.Connection) -> None:
    return None
