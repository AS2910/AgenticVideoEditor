"""0029 (G6): trust and safety.

    liveness_attempts   a random sentence read aloud before a speaker's voice
                        is cloned: who, which video and speaker, the sentence,
                        the recording's address, the result and why
    abuse_reports       a report from anyone (no account): where, what kind,
                        the details, an optional contact, its state
    data_requests       an owner's data export (an Activity job) or deletion
                        request, kept as a record
    provenance_marks    each export's invisible mark and its manifest, so a
                        file found elsewhere can be traced to its export

`down` drops the four tables (nothing refers to them)."""
from __future__ import annotations

from app.store.migrations._util import tables

TABLES = ("liveness_attempts", "abuse_reports", "data_requests", "provenance_marks")


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS liveness_attempts (
    id           TEXT PRIMARY KEY,
    owner        TEXT NOT NULL,
    video_id     TEXT NOT NULL,
    speaker      TEXT,
    sentence     TEXT NOT NULL,
    audio_sha    TEXT,
    status       TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    provider     TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    checked_at   TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS liveness_by_video ON liveness_attempts (video_id, status)")
    conn.execute("""CREATE TABLE IF NOT EXISTS abuse_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    location    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    details     TEXT NOT NULL DEFAULT '',
    contact     TEXT NOT NULL DEFAULT '',
    reporter    TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS data_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    job_id      TEXT,
    created_at  TEXT NOT NULL,
    done_at     TEXT
)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS provenance_marks (
    mark        TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    video_id    TEXT NOT NULL,
    file        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    manifest    TEXT NOT NULL,
    created_at  TEXT NOT NULL
)""")


def down(conn) -> None:
    have = tables(conn)
    conn.execute("DROP INDEX IF EXISTS liveness_by_video")
    for table in TABLES:
        if table in have:
            conn.execute(f"DROP TABLE {table}")
