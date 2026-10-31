"""0050 (voice consent V1, step 4): the held lines' review, on `line_checks`.

    reason         the check's one plain sentence (the model's, or which rules hit)
    review_state   '' for pass and block; waiting | approved | rejected | expired for a held line
    reviewed_by    the admin who decided ('auto' when 48 hours ran out)
    reviewed_at    when
    review_reason  the admin's reason (required), kept with the audit trail's copy
    model_ms       how long the check model took for the call that answered this line

Numbered 0050, not 0049, so step 5 (built the same night) can take 0049
without colliding (gaps are allowed). Additive; `down` drops the columns and
refuses while any line has been held, since that is evidence.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables

COLUMNS = (
    ("reason", "TEXT NOT NULL DEFAULT ''"),
    ("review_state", "TEXT NOT NULL DEFAULT ''"),
    ("reviewed_by", "TEXT"),
    ("reviewed_at", "TEXT"),
    ("review_reason", "TEXT NOT NULL DEFAULT ''"),
    ("model_ms", "INTEGER"),
)
INDEX = "line_checks_review"


def up(conn) -> None:
    if "line_checks" not in tables(conn):
        return
    for name, definition in COLUMNS:
        add_column(conn, "line_checks", name, definition)
    conn.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON line_checks (review_state, created_at)")


def down(conn) -> None:
    if "line_checks" not in tables(conn) or "review_state" not in columns(conn, "line_checks"):
        return
    n = conn.execute("SELECT COUNT(*) FROM line_checks WHERE review_state != ''").fetchone()[0]
    if n:
        raise RuntimeError(f"line_checks holds {n} held line(s); refusing to drop their review (restore a backup instead)")
    conn.execute(f"DROP INDEX IF EXISTS {INDEX}")
    for name, _ in reversed(COLUMNS):
        drop_column(conn, "line_checks", name)
