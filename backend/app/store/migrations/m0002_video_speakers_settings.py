"""0002: a video's speakers (Phase 11) and its own settings (Phase 12)."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column

COLUMNS = (
    ("videos", "speakers", "TEXT NOT NULL DEFAULT '{}'"),     # JSON: label -> {name, voice_id}
    ("videos", "settings", "TEXT NOT NULL DEFAULT '{}'"),     # JSON: per-video preferences
)


def up(conn) -> None:
    for table, column, definition in COLUMNS:
        add_column(conn, table, column, definition)


def down(conn) -> None:
    for table, column, _ in reversed(COLUMNS):
        drop_column(conn, table, column)
