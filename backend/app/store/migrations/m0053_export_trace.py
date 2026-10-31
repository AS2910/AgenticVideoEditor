"""0053 (voice consent V1, step 7): what Trace needs on each export's mark.

`provenance_marks` (0029) gains:

    export_id               the export the file belongs to (a batch export's id, or
                            the Export page file's own `ve_` id); also in the file's
                            container metadata and its manifest
    ai_voice                1 when the file contains a cloned voice
    label_on                1 when the "AI voice" label was drawn in
    export_attestation_id   the export reminder's confirmation that let it out
    voices                  JSON list of the cloned voice ids in it
    takes                   JSON list of the take ids its edits play (the synthesis
                            log rows behind it)

Numbered 0053, one of the numbers step 1 left for this run's steps (gaps are
allowed). Additive; `down` drops the columns and refuses while any mark carries
an export id, since that is evidence (restore a backup instead).
"""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables

COLUMNS = (
    ("export_id", "TEXT NOT NULL DEFAULT ''"),
    ("ai_voice", "INTEGER NOT NULL DEFAULT 0"),
    ("label_on", "INTEGER NOT NULL DEFAULT 0"),
    ("export_attestation_id", "TEXT"),
    ("voices", "TEXT NOT NULL DEFAULT '[]'"),
    ("takes", "TEXT NOT NULL DEFAULT '[]'"),
)
INDEX = "provenance_marks_by_export"


def up(conn) -> None:
    if "provenance_marks" not in tables(conn):
        return
    for name, definition in COLUMNS:
        add_column(conn, "provenance_marks", name, definition)
    conn.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON provenance_marks (export_id)")


def down(conn) -> None:
    if "provenance_marks" not in tables(conn) or "export_id" not in columns(conn, "provenance_marks"):
        return
    n = conn.execute("SELECT COUNT(*) FROM provenance_marks WHERE export_id != ''").fetchone()[0]
    if n:
        raise RuntimeError(f"provenance_marks holds {n} traced export(s); refusing to drop their trace (restore a backup instead)")
    conn.execute(f"DROP INDEX IF EXISTS {INDEX}")
    for name, _ in reversed(COLUMNS):
        drop_column(conn, "provenance_marks", name)
