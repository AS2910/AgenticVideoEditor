"""0004: Folders: the folder a video is in, and the folder at the time of a charge."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column

COLUMNS = (
    ("videos", "project_id", "TEXT"),                         # NULL = standalone
    ("usage", "folder_id", "TEXT"),
)


def up(conn) -> None:
    for table, column, definition in COLUMNS:
        add_column(conn, table, column, definition)


def down(conn) -> None:
    for table, column, _ in reversed(COLUMNS):
        drop_column(conn, table, column)
