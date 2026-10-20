"""0007 (FLAGS): feature flags, on per owner. A row overrides the default
(on for the owners in AVE_FLAG_OWNERS); see app/flags.py."""
from __future__ import annotations


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS feature_flags (
    flag       TEXT NOT NULL,          -- e.g. "projects.batch", "golive.g2"
    owner      TEXT NOT NULL,
    enabled    INTEGER NOT NULL,       -- 0 | 1
    updated_at TEXT NOT NULL,
    PRIMARY KEY (flag, owner)
)""")


def down(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS feature_flags")
