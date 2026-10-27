"""0047 (run 5 item 7): votes on the voice A/B listening page (`#admin/voice-ab`).

    voice_ab_votes  one row per admin per trial: which of the two takes sounded
                    better to them (old | new method, or same), which one they
                    heard as A (the order is blind and differs per person), and when.

Numbered 0047, not the next free number, so items built the same night can
each take their own without colliding (gaps are allowed). Admin-only and not
per workspace, so no RLS policy. `down` refuses while it holds rows.
"""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS voice_ab_votes (
    run         TEXT NOT NULL,           -- the eval run the trial belongs to
    trial       TEXT NOT NULL,
    voter       TEXT NOT NULL,           -- the signed-in admin
    picked      TEXT NOT NULL,           -- old | new | same
    heard_as_a  TEXT NOT NULL,           -- old | new: which method was A for them
    at          TEXT NOT NULL,
    PRIMARY KEY (run, trial, voter)
)""")


def down(conn) -> None:
    if "voice_ab_votes" not in tables(conn):
        return
    n = conn.execute("SELECT COUNT(*) FROM voice_ab_votes").fetchone()[0]
    if n:
        raise RuntimeError(f"voice_ab_votes holds {n} row(s); refusing to drop it (restore a backup instead)")
    conn.execute("DROP TABLE voice_ab_votes")
