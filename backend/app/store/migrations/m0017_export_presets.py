"""0017 (B3): export presets on a project. Each is a name, a platform frame
(youtube 16:9, reels 9:16, feed 1:1), a codec, a loudness target in LUFS,
burned-in captions on or off, and a file name pattern; `position` keeps the
order the user sees. The three defaults are written the first time a
project's presets are read (app/store/presets.py), not here."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS export_presets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,        -- f<n>
    name         TEXT NOT NULL,
    platform     TEXT NOT NULL,        -- youtube | reels | feed
    codec        TEXT NOT NULL DEFAULT 'h264',   -- h264 | hevc
    loudness     REAL NOT NULL DEFAULT -14,      -- -14 web | -16 general | -24 broadcast
    captions     INTEGER NOT NULL DEFAULT 0,
    pattern      TEXT NOT NULL,        -- {project}_{video}_{lang}_{preset}_v{version}
    position     INTEGER NOT NULL DEFAULT 0,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    workspace_id TEXT
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS export_presets_by_project ON export_presets (project_id, position, id)")


def down(conn) -> None:
    conn.execute("DROP INDEX IF EXISTS export_presets_by_project")
    if "export_presets" in tables(conn):
        conn.execute("DROP TABLE export_presets")
