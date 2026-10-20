"""The purge (F8): what has been in the Bin longer than `older_than_days`
goes for good. Videos and projects: their rows, what was made on them, their
activity and their stored media; voices of one's own: the entry and its
sample. A voice at the vendor goes too (through `delete_voice`) unless some
live voice list still holds it. Charges are never deleted: each purged item
leaves its name in `purged_items`, so Usage still shows what it was.

Not scheduled: run it by hand.

    python -m app.purge --days 30 --dry-run      # what would go
    python -m app.purge --days 30                # do it
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.store.db import PROJECT_TABLES, Database
from app.timefmt import iso, now_iso

log = logging.getLogger("ave")


@dataclass
class PurgeReport:
    dry_run: bool
    cutoff: str
    videos: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    voices: list[str] = field(default_factory=list)          # "<owner>:<voice_id>"
    storage: list[str] = field(default_factory=list)         # paths removed (or that would be)
    vendor_voices: list[str] = field(default_factory=list)   # deleted at the vendor (or would be)
    vendor_failed: list[str] = field(default_factory=list)   # still at the vendor: remove by hand

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _cutoff(older_than_days: float, now: datetime | None) -> str:
    return iso((now or datetime.now(timezone.utc)) - timedelta(days=older_than_days))


def _meta(c, key: str, default):
    row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _held_voice_ids(c, voices: set[tuple[str, str]], projects: set[str], videos: set[str]) -> set[str]:
    """Every vendor voice something staying still holds: someone's own list
    (a voice in the Bin not due yet included), a project's shared voices, a
    video's made voices and clones. What is being purged now holds nothing."""
    held: set[str] = set()
    for key, value in c.execute("SELECT key, value FROM meta WHERE key LIKE 'my_voices:%'"):
        owner = key.split(":", 1)[1]
        held |= {v.get("voice_id") for v in json.loads(value) if (owner, v.get("voice_id")) not in voices}
    for key, value in c.execute("SELECT key, value FROM meta WHERE key LIKE 'project_voices:%'"):
        if key.split(":", 1)[1] not in projects:
            held |= {v.get("voice_id") for v in json.loads(value)}
    for row in c.execute("SELECT id, settings, speakers FROM videos"):
        if row["id"] not in videos:
            held |= {m.get("voice_id") for m in json.loads(row["settings"] or "{}").get("made_voices") or []}
            held |= {s.get("clone_voice_id") for s in json.loads(row["speakers"] or "{}").values()}
    held.discard(None)
    return held


def purge(db: Database, artifacts_root: str | Path, older_than_days: float = 30, *, dry_run: bool = False,
          delete_voice: Callable[[str], None] | None = None, now: datetime | None = None) -> PurgeReport:
    root = Path(artifacts_root)
    cutoff = _cutoff(older_than_days, now)
    report = PurgeReport(dry_run=dry_run, cutoff=cutoff)
    vendor: set[str] = set()
    with db.tx() as c:
        videos = c.execute("SELECT * FROM videos WHERE deleted_at IS NOT NULL AND deleted_at < ? ORDER BY id", (cutoff,)).fetchall()
        projects = c.execute("SELECT * FROM projects WHERE deleted_at IS NOT NULL AND deleted_at < ? ORDER BY id", (cutoff,)).fetchall()
        voices: list[tuple[str, dict]] = []
        for key, value in c.execute("SELECT key, value FROM meta WHERE key LIKE 'my_voices:%'").fetchall():
            owner = key.split(":", 1)[1]
            voices += [(owner, v) for v in json.loads(value) if v.get("deleted_at") and v["deleted_at"] < cutoff]
        held = _held_voice_ids(c, {(owner, v["voice_id"]) for owner, v in voices},
                               {p["id"] for p in projects}, {v["id"] for v in videos})

        for v in videos:
            vid = v["id"]
            report.videos.append(vid)
            settings = json.loads(v["settings"] or "{}")
            vendor |= {m.get("voice_id") for m in settings.get("made_voices") or []}
            vendor |= {s.get("clone_voice_id") for s in json.loads(v["speakers"] or "{}").values()}
            if (root / vid).exists():
                report.storage.append(str(root / vid))
            if dry_run:
                continue
            name = json.loads(v["source"] or "{}").get("filename") or vid
            _tombstone(c, "video", vid, name, v["owner"], v["project_id"], v["workspace_id"], v["deleted_at"])
            c.execute("DELETE FROM videos WHERE id = ?", (vid,))
            for table in PROJECT_TABLES:
                if table != "usage":
                    c.execute(f"DELETE FROM {table} WHERE project_id = ?", (vid,))
            c.execute("DELETE FROM project_events WHERE video_id = ?", (vid,))
            c.execute("DELETE FROM share_tokens WHERE scope = 'video' AND target = ?", (vid,))

        for p in projects:
            pid = p["id"]
            report.projects.append(pid)
            vendor |= {v["voice_id"] for v in _meta(c, f"project_voices:{pid}", [])}
            if (root / "projects" / pid).exists():
                report.storage.append(str(root / "projects" / pid))
            if dry_run:
                continue
            _tombstone(c, "project", pid, p["name"], p["owner"], None, p["workspace_id"], p["deleted_at"])
            c.execute("DELETE FROM projects WHERE id = ?", (pid,))
            for table in ("project_briefs", "project_rules", "project_events", "project_checks", "project_issues",
                          "project_issue_ignores", "share_tokens", "export_presets"):
                c.execute(f"DELETE FROM {table} WHERE project_id = ?", (pid,))
            # B3: the project's batch exports (their files go with the project's folder).
            for export_id in _meta(c, f"exports:{pid}", []):
                c.execute("DELETE FROM meta WHERE key = ?", (f"export:{export_id}",))
            for prefix in ("project_voices", "project_files", "brief_suggestions", "exports", "export_presets_seeded"):
                c.execute("DELETE FROM meta WHERE key = ?", (f"{prefix}:{pid}",))
            # A live video still filed here (it should not be) becomes standalone.
            c.execute("UPDATE videos SET project_id = NULL WHERE project_id = ?", (pid,))

        by_owner: dict[str, set[str]] = {}
        for owner, v in voices:
            report.voices.append(f"{owner}:{v['voice_id']}")
            vendor.add(v["voice_id"])
            by_owner.setdefault(owner, set()).add(v["voice_id"])
        for owner, ids in by_owner.items():
            mine = _meta(c, f"my_voices:{owner}", [])
            gone = [v for v in mine if v["voice_id"] in ids]
            left = [v for v in mine if v["voice_id"] not in ids]
            designs = _meta(c, f"designs:{owner}", {})
            in_use = {v.get("sample_sha") for v in left} | {d.get("sha256") for d in designs.values()}
            for value in [r[0] for r in c.execute("SELECT value FROM meta WHERE key LIKE 'project_voices:%'")]:
                in_use |= {v.get("sample_sha") for v in json.loads(value)}
            for v in gone:
                sha = v.get("sample_sha")
                if sha and sha not in in_use:
                    report.storage += [str(p) for p in sorted((root / f"user-{owner}").glob(f"{sha}.*"))]
                if not dry_run:
                    _tombstone(c, "voice", f"{owner}:{v['voice_id']}", v.get("name") or v["voice_id"], owner, None, None,
                               v.get("deleted_at"))
            if not dry_run:
                c.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(left), f"my_voices:{owner}"))

        report.vendor_voices = sorted(v for v in vendor if v and v not in held)
        if dry_run:
            return report

    # Outside the transaction: files and vendor calls cannot roll back, so they
    # go only once the rows are gone for good.
    for path in report.storage:
        target = Path(path)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    done = []
    for voice_id in report.vendor_voices:
        if delete_voice is None:
            report.vendor_failed.append(voice_id)
            continue
        try:
            delete_voice(voice_id)
            done.append(voice_id)
        except Exception as exc:  # noqa: BLE001 — one voice the vendor kept never stops the purge
            log.warning("purge: voice %s is still at the vendor: %s", voice_id, exc)
            report.vendor_failed.append(voice_id)
    report.vendor_voices = done
    return report


def _tombstone(c, kind: str, item_id: str, name: str, owner: str, project_id: str | None,
               workspace_id: str | None, deleted_at: str | None) -> None:
    c.execute("INSERT OR REPLACE INTO purged_items (kind, item_id, name, owner, project_id, workspace_id, deleted_at, purged_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (kind, item_id, name, owner, project_id, workspace_id, deleted_at, now_iso()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.purge",
                                     description="Remove for good what has been in the Bin longer than --days.")
    parser.add_argument("--days", type=float, default=30, help="how long an item stays in the Bin (default 30)")
    parser.add_argument("--dry-run", action="store_true", help="list what would go, change nothing")
    parser.add_argument("--db", help="the SQLite file (default: the app's, under AVE_DATA_DIR)")
    parser.add_argument("--data-dir", help="the data directory holding artifacts/ (default: AVE_DATA_DIR)")
    args = parser.parse_args(argv)
    from app.config import load_settings
    settings = load_settings()
    data_dir = Path(args.data_dir) if args.data_dir else settings.data_dir
    db = Database(args.db or data_dir / "ave.db")
    delete_voice = None if args.dry_run else _vendor_delete(settings, db, data_dir)
    report = purge(db, data_dir / "artifacts", args.days, dry_run=args.dry_run, delete_voice=delete_voice)
    print(json.dumps(report.to_dict(), indent=2))
    return 0


def _vendor_delete(settings, db: Database, data_dir: Path) -> Callable[[str], None] | None:
    """The voice vendor's delete, as the app would make it (None under the mock)."""
    from app.adapters.selection import select_voice
    from app.budget import VoiceBudget
    from app.store.artifacts import ArtifactStore
    from app.usage import Ledger
    budget = VoiceBudget(ceiling=settings.voice_budget_chars, ledger=Ledger(db, ceiling_usd=settings.project_budget_usd),
                         usd_per_1k=settings.elevenlabs_usd_per_1k)
    adapter, _ = select_voice(settings, ArtifactStore(data_dir / "artifacts"), budget)
    return getattr(adapter, "delete_voice", None)


if __name__ == "__main__":
    sys.exit(main())
