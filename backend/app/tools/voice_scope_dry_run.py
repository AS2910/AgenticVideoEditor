"""Voice consent V1, step 1: migration 0048 on a copy, before it is applied.

    python -m app.tools.voice_scope_dry_run --db backend/var/ave.db [--json]

Copies the database (sqlite3's online backup; a running server is fine) into
a temp dir and never touches the original. On the copy: every step before
0048 up, then the counts per row of the plan's "Migrating existing voices"
table (what `up` would write), then 0048 up for real, then a check that
nothing was lost (every table and every JSON voice list the same as before,
one voice record per voice) and that 0048's down puts the copy back as it was.
Nothing calls the voice vendor: a clone whose video is gone is only counted as
queued for deletion. Exits 1 on any difference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from app.store import migrate
from app.store.migrations import m0048_voice_consent as m0048

VERSION = 48
LABELS = {
    "designed_or_stock": "Designed or stock voice -> library, unchanged",
    "clone_verified": "Clone with a passed own-voice check -> library, linked to that check",
    "clone_video": "Any other clone -> video scope, tied to the video it was made from",
    "clone_source_deleted": "Clone whose source video is deleted -> withdrawn, vendor delete queued",
    "upload": "Uploaded recording of your own voice -> library (no check linked)",
    "clone_video_in_bin": "  of the video-scoped clones, source video in the Bin",
}


def _fingerprint(conn) -> dict[str, str]:
    """A hash of every table (row count and content) but the migrations' own record."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations' "
        "AND name NOT LIKE 'search_fts%'")]
    out = {}
    for n in sorted(names):
        h = hashlib.sha256()
        for row in conn.execute(f"SELECT * FROM {n} ORDER BY 1"):
            h.update(repr(tuple(row)).encode())
        out[n] = h.hexdigest()
    return out


def run(source: Path) -> dict:
    report: dict = {"problems": []}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "ave.db"
        with sqlite3.connect(source) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        conn = migrate.connect(str(copy))
        try:
            done = migrate.applied(conn)
            if VERSION in done:
                report["already_applied"] = True
                migrate.down_to(conn, VERSION - 1)
            before_steps = [m for m in migrate.all_migrations() if m.version < VERSION and m.version not in migrate.applied(conn)]
            for m in before_steps:
                migrate._run(conn, m, "up")
            before = _fingerprint(conn)
            rows = m0048.classify(conn)
            report["counts"] = m0048.counts(rows)
            report["voices"] = [{k: r[k] for k in ("voice_id", "owner", "kind", "row", "scope", "status", "source_video_id",
                                                     "speaker_label", "verified_consent_id", "vendor_state")} for r in rows]
            step = next(m for m in migrate.all_migrations() if m.version == VERSION)
            written = migrate._run(conn, step, "up")
            if written != report["counts"]:
                report["problems"].append(f"up wrote {written}, the dry run counted {report['counts']}")
            after = _fingerprint(conn)
            changed = [t for t in before if before[t] != after.get(t)]
            if changed:
                report["problems"].append(f"tables changed by up (it only adds): {changed}")
            n = conn.execute("SELECT COUNT(*) FROM voice_records").fetchone()[0]
            if n != len(rows):
                report["problems"].append(f"{n} voice records for {len(rows)} voices")
            migrate._run(conn, step, "down")
            restored = _fingerprint(conn)
            if restored != before:
                report["problems"].append("down did not restore the copy: "
                                          + ", ".join(sorted(set(restored) ^ set(before)) or
                                                      [t for t in before if before[t] != restored.get(t)]))
            report["tables_compared"] = len(before)
        finally:
            conn.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.voice_scope_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="the database to read (copied first, never changed)")
    parser.add_argument("--json", action="store_true", help="print the whole report as JSON")
    args = parser.parse_args(argv)
    report = run(Path(args.db))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Migration 0048 on a copy of {args.db}:")
        for key, label in LABELS.items():
            print(f"  {report['counts'].get(key, 0):>4}  {label}")
        print(f"  {len(report['voices']):>4}  voices in all; {report.get('tables_compared', 0)} tables compared")
        for p in report["problems"]:
            print(f"  PROBLEM: {p}")
        if not report["problems"]:
            print("  nothing lost; down restores the copy")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
