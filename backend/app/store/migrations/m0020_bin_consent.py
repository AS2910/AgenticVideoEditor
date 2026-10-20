"""0020 (D3): the Bin keeps consent. `purged_items.consent` holds the
consent record of a purged video (the speaker's consent to clone their
voice) or voice of one's own, as JSON `{"granted_at", "approximate"}`, so
the record outlives the item for the legal retention period. NULL when the
item had none.

`down` refuses while any purged item carries a consent record: dropping the
column would lose it."""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables


def up(conn) -> None:
    add_column(conn, "purged_items", "consent", "TEXT")


def down(conn) -> None:
    if "purged_items" in tables(conn) and "consent" in columns(conn, "purged_items"):
        n = conn.execute("SELECT COUNT(*) FROM purged_items WHERE consent IS NOT NULL").fetchone()[0]
        if n:
            raise RuntimeError(f"{n} purged item(s) keep a consent record; refusing to drop it")
    drop_column(conn, "purged_items", "consent")
