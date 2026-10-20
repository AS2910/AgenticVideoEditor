"""0005: spend scopes: the turn that caused a charge (NULL outside a turn)."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column


def up(conn) -> None:
    add_column(conn, "usage", "turn_id", "TEXT")


def down(conn) -> None:
    drop_column(conn, "usage", "turn_id")
