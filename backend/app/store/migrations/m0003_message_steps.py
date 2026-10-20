"""0003: Phase 20 chat steps: a message's kind, what a step cost, a card's facts."""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column

COLUMNS = (
    ("messages", "kind", "TEXT NOT NULL DEFAULT 'say'"),      # "say" | "step"
    ("messages", "cost", "REAL"),                             # what a step cost, in dollars
    ("messages", "data", "TEXT"),                             # Phase 20b: a card's facts (voice previews), JSON
)


def up(conn) -> None:
    for table, column, definition in COLUMNS:
        add_column(conn, table, column, definition)


def down(conn) -> None:
    for table, column, _ in reversed(COLUMNS):
        drop_column(conn, table, column)
