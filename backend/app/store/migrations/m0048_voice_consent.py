"""0048 (voice consent V1, step 1): a scope for every voice Voltage made, and
the five records the voice guard keeps (app.safety.voice_guard).

Voices are not one table: they live in JSON lists (`meta` my_voices:<owner>
and project_voices:<project>, a video's `settings.made_voices`, and each
speaker's `clone_voice_id` in `videos.speakers`). Those lists stay exactly as
they are; this step adds one row per vendor voice beside them:

    voice_records      voice_id (the vendor's id, the key), owner, workspace_id,
                       kind (cloned | recorded | designed | library), scope
                       (video: locked to its source video's family; library:
                       usable anywhere, in My voices), source_video_id,
                       speaker_label (the diarization label, "_" for a whole
                       clip), speaker_name, verified_consent_id (the passed
                       own-voice check, `liveness_attempts.id`, that allowed
                       library scope), status (active | suspended | withdrawn),
                       status_reason, status_by, origin (migration | clone |
                       upload | promote | design), migration_row (which row of
                       the plan's table this voice was migrated by), vendor_state
                       (live | delete_queued | deleted), created_at, updated_at

and the five tables of the plan:

    voice_attestations   the user's word on whose voice it is, per voice (or
                         speaker, before the clone is made) and statement version
    export_attestations  the export reminder confirmed, for what it covered
    line_checks          every line checked before it is voiced (the text only
                         when blocked or held; a passing line keeps its hash)
    synthesis_log        every take voiced, after the vendor call
    no_go_voices         public figures and reported voices (admin managed)

Every table carries `workspace_id`; all but no_go_voices (one list for the
whole platform, its workspace NULL) get 0034's RLS policy on Postgres.

Existing voices are migrated per the plan's table (`classify` is the rule, and
`python -m app.tools.voice_scope_dry_run` reports its counts on a copy):

    designed_or_stock      a designed voice or one added from the library: library
    clone_verified         a clone whose video has a passed own-voice check (the
                           real gate, method 'verified'): library, linked to it
    clone_video            any other clone: video scope, tied to the video it was
                           made from (a video in the Bin counts as there: the purge
                           deletes its voices as it always did)
    clone_source_deleted   a clone whose source video is gone: withdrawn, and its
                           vendor voice queued for deletion (vendor_state
                           delete_queued). Nothing here calls the vendor; the app
                           deletes queued voices when it starts (the guard's
                           drain_vendor_deletes), only for an owner with
                           `voices.cloning_verified` on
    upload                 a recording the user uploaded as their own voice (the
                           admin-opened `voices.cloning` path): library, with no
                           check linked (the plan has no row for it; DECISIONS.md)

`up` is idempotent (a voice with a row keeps it) and returns the counts.
`down` drops the six tables; the JSON lists were never touched, so the
database is as it was. It refuses while any record holds a person's word or
an action (an attestation, a confirmation, a line check, a synthesis, a no-go
entry, or a voice record a person or the app changed after the migration):
that is evidence; restore a backup instead.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.store.migrations._util import columns, tables
from app.store.pg import is_pg

ROWS = ("designed_or_stock", "clone_verified", "clone_video", "clone_source_deleted", "upload")

TABLES = {
    "voice_records": """CREATE TABLE IF NOT EXISTS voice_records (
    voice_id            TEXT PRIMARY KEY,
    owner               TEXT NOT NULL,
    workspace_id        TEXT,
    kind                TEXT NOT NULL,                    -- cloned | recorded | designed | library
    scope               TEXT NOT NULL,                    -- video | library
    source_video_id     TEXT,
    speaker_label       TEXT,
    speaker_name        TEXT,
    verified_consent_id TEXT,
    status              TEXT NOT NULL DEFAULT 'active',   -- active | suspended | withdrawn
    status_reason       TEXT NOT NULL DEFAULT '',
    status_by           TEXT,
    origin              TEXT NOT NULL,                    -- migration | clone | upload | promote | design
    migration_row       TEXT,
    vendor_state        TEXT NOT NULL DEFAULT 'live',     -- live | delete_queued | deleted
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
)""",
    "voice_attestations": """CREATE TABLE IF NOT EXISTS voice_attestations (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT,
    owner               TEXT NOT NULL,
    video_id            TEXT NOT NULL,
    voice_id            TEXT,
    speaker_label       TEXT,
    choice              TEXT NOT NULL,                    -- my_voice | have_permission
    statement_version   TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    ip                  TEXT,
    user_agent          TEXT
)""",
    "export_attestations": """CREATE TABLE IF NOT EXISTS export_attestations (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT,
    export_id           TEXT NOT NULL,
    owner               TEXT NOT NULL,
    voices_used         TEXT NOT NULL,                    -- JSON list of voice ids
    covers              TEXT NOT NULL,                    -- JSON list of video_id:content keys
    statement_version   TEXT NOT NULL,
    label_on            INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    ip                  TEXT
)""",
    "line_checks": """CREATE TABLE IF NOT EXISTS line_checks (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT,
    owner               TEXT NOT NULL,
    video_id            TEXT,
    voice_id            TEXT,
    text                TEXT,                             -- only for block | review
    text_hash           TEXT NOT NULL,
    verdict             TEXT NOT NULL,                    -- pass | block | review
    categories          TEXT NOT NULL DEFAULT '[]',
    model               TEXT NOT NULL DEFAULT '',
    rule_hits           TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
)""",
    "synthesis_log": """CREATE TABLE IF NOT EXISTS synthesis_log (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT,
    owner               TEXT NOT NULL,
    video_id            TEXT,
    voice_id            TEXT NOT NULL,
    attestation_id      TEXT,
    line_check_id       TEXT,
    text_hash           TEXT NOT NULL,
    take_id             TEXT,
    cost_usd            REAL,
    created_at          TEXT NOT NULL
)""",
    "no_go_voices": """CREATE TABLE IF NOT EXISTS no_go_voices (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    reason              TEXT NOT NULL DEFAULT '',
    reference_embedding TEXT,                             -- JSON list of floats (step 5)
    added_by            TEXT,
    created_at          TEXT NOT NULL,
    workspace_id        TEXT                              -- NULL: the whole platform (admins keep one list)
)""",
}
INDEXES = (
    "CREATE INDEX IF NOT EXISTS voice_records_by_owner ON voice_records (owner, origin, created_at)",
    "CREATE INDEX IF NOT EXISTS voice_records_by_video ON voice_records (source_video_id)",
    "CREATE INDEX IF NOT EXISTS voice_attestations_by_owner ON voice_attestations (owner, statement_version)",
    "CREATE INDEX IF NOT EXISTS export_attestations_by_owner ON export_attestations (owner, export_id)",
    "CREATE INDEX IF NOT EXISTS line_checks_by_owner ON line_checks (owner, verdict, created_at)",
    "CREATE INDEX IF NOT EXISTS synthesis_log_by_owner ON synthesis_log (owner, created_at)",
)
SCOPED = ("voice_records", "voice_attestations", "export_attestations", "line_checks", "synthesis_log")
# Kept as people's word or actions: `down` refuses while these hold rows.
EVIDENCE = ("voice_attestations", "export_attestations", "line_checks", "synthesis_log", "no_go_voices")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(text, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _verified_checks(conn) -> list[dict]:
    """Passed own-voice checks of the real gate (method 'verified'); the stand-in check of 0029 does not count."""
    if "liveness_attempts" not in tables(conn) or "method" not in columns(conn, "liveness_attempts"):
        return []
    rows = conn.execute("SELECT id, owner, video_id, speaker, created_at FROM liveness_attempts "
                        "WHERE status = 'passed' AND method = 'verified' ORDER BY created_at, id").fetchall()
    return [{"id": r[0], "owner": r[1], "video_id": r[2], "speaker": r[3]} for r in rows]


def _check_for(checks: list[dict], owner: str, video_id: str, label: str | None, name: str | None) -> str | None:
    for c in checks:
        if c["owner"] == owner and c["video_id"] == video_id and (not c["speaker"] or c["speaker"] in (label, name)):
            return c["id"]
    return None


def inventory(conn) -> list[dict]:
    """Every vendor voice the JSON lists and videos hold, one entry per voice id
    (the first place it is found that says where it came from wins)."""
    videos: dict[str, dict] = {}
    has_deleted = "deleted_at" in columns(conn, "videos")
    for r in conn.execute("SELECT id, owner, speakers, settings" + (", deleted_at" if has_deleted else "") + " FROM videos").fetchall():
        videos[r[0]] = {"owner": r[1], "speakers": _json(r[2], {}), "settings": _json(r[3], {}),
                        "deleted": bool(r[4]) if has_deleted else False}
    found: dict[str, dict] = {}

    def add(voice_id, owner, kind, video_id=None, label=None, name=None):
        if not voice_id or not owner:
            return
        have = found.get(voice_id)
        if have is not None and (have["source_video_id"] or not video_id):
            return
        found[voice_id] = {"voice_id": voice_id, "owner": owner, "kind": kind, "source_video_id": video_id,
                           "speaker_label": label, "speaker_name": name}

    for vid, v in sorted(videos.items()):
        for key, entry in sorted((v["speakers"] or {}).items()):
            if isinstance(entry, dict) and entry.get("clone_voice_id"):
                add(entry["clone_voice_id"], v["owner"], "cloned", vid, key, entry.get("name"))
        for m in (v["settings"] or {}).get("made_voices") or []:
            if isinstance(m, dict):
                add(m.get("voice_id"), v["owner"], m.get("kind") or "designed")

    def from_list(owner, items):
        for e in items if isinstance(items, list) else []:
            if not isinstance(e, dict):
                continue
            kind = e.get("kind") or "recorded"
            src = e.get("source") if isinstance(e.get("source"), dict) else {}
            if kind == "cloned":
                add(e.get("voice_id"), owner, "cloned", src.get("video_id"), src.get("label"), e.get("name"))
            else:
                add(e.get("voice_id"), owner, kind)

    for key, value in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'my_voices:%' ORDER BY key").fetchall():
        from_list(key[len("my_voices:"):], _json(value, []))
    owners = {r[0]: r[1] for r in conn.execute("SELECT id, owner FROM projects").fetchall()} if "projects" in tables(conn) else {}
    for key, value in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'project_voices:%' ORDER BY key").fetchall():
        owner = owners.get(key[len("project_voices:"):])
        if owner:
            from_list(owner, _json(value, []))
    return [found[k] for k in sorted(found)]


def classify(conn) -> list[dict]:
    """The plan's "Migrating existing voices" table, applied: each voice with
    its scope, status, link and the row that decided it. Reads only."""
    videos = {r[0]: r[1] for r in conn.execute(
        "SELECT id, " + ("deleted_at" if "deleted_at" in columns(conn, "videos") else "NULL") + " FROM videos").fetchall()}
    checks = _verified_checks(conn)
    out = []
    for v in inventory(conn):
        row = dict(v, scope="library", status="active", verified_consent_id=None, vendor_state="live", binned=False)
        if v["kind"] == "cloned":
            src = v["source_video_id"]
            consent = _check_for(checks, v["owner"], src, v["speaker_label"], v["speaker_name"]) if src else None
            if not src or src not in videos:
                row.update(row="clone_source_deleted", scope="video", status="withdrawn", vendor_state="delete_queued")
            elif consent:
                row.update(row="clone_verified", verified_consent_id=consent)
            else:
                row.update(row="clone_video", scope="video", binned=bool(videos[src]))
        elif v["kind"] == "recorded":
            row.update(row="upload")
        else:
            row.update(row="designed_or_stock")
        out.append(row)
    return out


def counts(rows: list[dict]) -> dict[str, int]:
    out = {name: 0 for name in ROWS}
    for r in rows:
        out[r["row"]] += 1
    out["clone_video_in_bin"] = sum(1 for r in rows if r["row"] == "clone_video" and r["binned"])
    return out


def up(conn) -> dict[str, int]:
    for ddl in TABLES.values():
        conn.execute(ddl)
    for ddl in INDEXES:
        conn.execute(ddl)
    if is_pg(conn):
        from app.store.migrations import m0034_row_level_security as m0034
        for table in SCOPED:
            m0034.apply(conn, table)
    have = {r[0] for r in conn.execute("SELECT voice_id FROM voice_records").fetchall()}
    rows = classify(conn)
    now = _now()
    for r in rows:
        if r["voice_id"] in have:
            continue
        conn.execute(
            "INSERT INTO voice_records (voice_id, owner, workspace_id, kind, scope, source_video_id, speaker_label, speaker_name, "
            "verified_consent_id, status, status_reason, origin, migration_row, vendor_state, created_at, updated_at) VALUES "
            "(?, ?, (SELECT id FROM workspaces WHERE owner = ? ORDER BY created_at, id LIMIT 1), ?, ?, ?, ?, ?, ?, ?, ?, "
            "'migration', ?, ?, ?, ?)",
            (r["voice_id"], r["owner"], r["owner"], r["kind"], r["scope"], r["source_video_id"], r["speaker_label"],
             r["speaker_name"], r["verified_consent_id"], r["status"],
             "source video deleted" if r["row"] == "clone_source_deleted" else "", r["row"], r["vendor_state"], now, now))
    return counts(rows)


def down(conn) -> None:
    there = tables(conn)
    for table in EVIDENCE:
        if table in there:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n:
                raise RuntimeError(f"{table} holds {n} row(s) of voice consent evidence; refusing to drop it "
                                   "(restore a backup instead)")
    if "voice_records" in there:
        n = conn.execute("SELECT COUNT(*) FROM voice_records WHERE origin != 'migration' OR updated_at != created_at").fetchone()[0]
        if n:
            raise RuntimeError(f"voice_records holds {n} voice(s) made or changed since the migration; refusing to drop "
                               "their scope and status (restore a backup instead)")
    for ddl in INDEXES:
        conn.execute("DROP INDEX IF EXISTS " + ddl.split(" IF NOT EXISTS ")[1].split(" ON ")[0])
    for table in TABLES:
        if table in there:
            if is_pg(conn) and table in SCOPED:
                conn.execute(f"DROP POLICY IF EXISTS ws_scope ON {table}")
            conn.execute(f"DROP TABLE {table}")
