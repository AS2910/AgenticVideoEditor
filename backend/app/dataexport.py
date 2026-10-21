"""G6: export an owner's data. A zip of JSON, one file per kind of record,
plus `media.json` listing every stored file by content address (the media
itself is not copied: it can be large, and each file is downloadable from
the app while the account exists).

    build(db, owner, artifacts_root, dest) -> {"files": [...], "rows": n}

Each table is read with the owner's rows only: their videos and everything
keyed by those videos, their projects and everything keyed by those, and the
person-keyed tables (notifications, feedback, billing, consent records kept
after a purge, analytics events, liveness attempts, data requests). Text
columns that hold JSON are decoded so the export reads as one document.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.timefmt import now_iso

# table -> how its rows belong to the owner
BY_VIDEO = ("candidates", "edits", "messages", "turns", "plans", "jobs", "usage")
BY_PROJECT = ("project_briefs", "project_rules", "project_events", "project_checks", "project_issues",
              "export_presets", "learned_items", "proposal_decisions", "share_tokens")
BY_PERSON = {"notifications": "recipient", "notification_settings": "recipient", "feedback": "owner",
             "billing_accounts": "owner", "credit_grants": "owner", "invoices": "owner", "purged_items": "owner",
             "analytics_events": "owner", "liveness_attempts": "owner", "data_requests": "owner", "pins": "owner",
             "project_templates": "owner", "review_comments": None}
JSONISH = ("body", "source", "transcript", "payload", "props", "data", "settings", "speakers", "consent", "detail",
           "context", "summary", "items", "lines", "snapshot")


def _tables(c) -> set[str]:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(c, table: str) -> list[str]:
    return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


def _row(r) -> dict:
    out = {}
    for k in r.keys():
        v = r[k]
        if k in JSONISH and isinstance(v, str) and v[:1] in "[{":
            try:
                v = json.loads(v)
            except ValueError:
                pass
        out[k] = v
    return out


def collect(db, owner: str) -> dict[str, list[dict]]:
    with db.tx() as c:
        have = _tables(c)
        videos = [_row(r) for r in c.execute("SELECT * FROM videos WHERE owner = ?", (owner,))]
        projects = [_row(r) for r in c.execute("SELECT * FROM projects WHERE owner = ?", (owner,))]
        vids = [v["id"] for v in videos]
        pids = [p["id"] for p in projects]
        out: dict[str, list[dict]] = {"videos": videos, "projects": projects}
        for table in BY_VIDEO:
            if table in have and vids:
                marks = ",".join("?" * len(vids))
                out[table] = [_row(r) for r in c.execute(f"SELECT * FROM {table} WHERE project_id IN ({marks})", vids)]
        for table in BY_PROJECT:
            if table not in have or not pids:
                continue
            column = "project_id" if "project_id" in _columns(c, table) else None
            if column:
                marks = ",".join("?" * len(pids))
                out[table] = [_row(r) for r in c.execute(f"SELECT * FROM {table} WHERE {column} IN ({marks})", pids)]
        for table, column in BY_PERSON.items():
            if table not in have:
                continue
            if column is None:          # review comments: on the owner's videos
                if vids and "video_id" in _columns(c, table):
                    marks = ",".join("?" * len(vids))
                    out[table] = [_row(r) for r in c.execute(f"SELECT * FROM {table} WHERE video_id IN ({marks})", vids)]
                continue
            if column in _columns(c, table):
                out[table] = [_row(r) for r in c.execute(f"SELECT * FROM {table} WHERE {column} = ?", (owner,))]
        mine = c.execute("SELECT value FROM meta WHERE key = ?", (f"my_voices:{owner}",)).fetchone()
        out["my_voices"] = json.loads(mine[0]) if mine and mine[0] else []
    return out


def _media(artifacts_root: Path, video_ids: list[str], owner: str) -> list[dict]:
    found = []
    for key in [*video_ids, f"user-{owner}"]:
        folder = artifacts_root / key
        if not folder.is_dir():
            continue
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                found.append({"store": key, "file": f.name, "bytes": f.stat().st_size,
                              "path": str(f.relative_to(artifacts_root))})
    return found


def build(db, owner: str, artifacts_root: Path, dest: Path) -> dict:
    data = collect(db, owner)
    media = _media(Path(artifacts_root), [v["id"] for v in data["videos"]], owner)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    names = []
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "Your Voltage data, exported " + now_iso() + ".\n"
                   "Each .json file holds one kind of record. media.json lists every stored file by its address;\n"
                   "the files themselves are not in this zip and can be downloaded from Voltage while your account exists.\n")
        for name, items in sorted(data.items()):
            z.writestr(f"{name}.json", json.dumps(items, indent=2, default=str))
            names.append(f"{name}.json")
            rows += len(items)
        z.writestr("media.json", json.dumps(media, indent=2))
        names.append("media.json")
    return {"files": names, "rows": rows, "media": len(media), "bytes": dest.stat().st_size}
