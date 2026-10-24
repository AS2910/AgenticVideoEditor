"""0039 (run 4, item 2): consent-verified cloning.

`liveness_attempts` (0029) gains what the real gate measured, so each consent
record carries its evidence:

    method          'verified' (the gate in app.safety.consent) or '' (the
                    stand-in check of 0029)
    heard           what Whisper heard, as text
    wer             its word error rate against the phrase
    similarity      SIM-o between the recording and the clone's source audio
    seconds         the recording's length
    rule            which rule decided: length | words | voice | unmeasured
    tip             what the person was told to try next
    asr_model       the transcriber's label (openai:whisper-1, or none)
    speaker_model   the speaker model (microsoft/wavlm-base-plus-sv)
    pass_at, review_from   the bands the decision used
    expires_at      a phrase not read by then is spent
    reviewed_by, review_reason, reviewed_at   an admin's decision on a
                    borderline attempt (status 'review' -> passed | failed);
                    the admin audit has it too

The admin queue reads `status = 'review'` (index liveness_by_status).
`down` refuses while any verified attempt exists (it is consent evidence);
restore a backup instead.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, columns, drop_column, tables

COLUMNS = (
    ("method", "TEXT NOT NULL DEFAULT ''"),
    ("heard", "TEXT"),
    ("wer", "REAL"),
    ("similarity", "REAL"),
    ("seconds", "REAL"),
    ("rule", "TEXT NOT NULL DEFAULT ''"),
    ("tip", "TEXT NOT NULL DEFAULT ''"),
    ("asr_model", "TEXT NOT NULL DEFAULT ''"),
    ("speaker_model", "TEXT NOT NULL DEFAULT ''"),
    ("pass_at", "REAL"),
    ("review_from", "REAL"),
    ("expires_at", "TEXT"),
    ("reviewed_by", "TEXT"),
    ("review_reason", "TEXT NOT NULL DEFAULT ''"),
    ("reviewed_at", "TEXT"),
)


def up(conn) -> None:
    for name, definition in COLUMNS:
        add_column(conn, "liveness_attempts", name, definition)
    conn.execute("CREATE INDEX IF NOT EXISTS liveness_by_status ON liveness_attempts (status, created_at)")


def down(conn) -> None:
    if "liveness_attempts" not in tables(conn):
        return
    if "method" in columns(conn, "liveness_attempts"):
        n = conn.execute("SELECT COUNT(*) FROM liveness_attempts WHERE method = 'verified'").fetchone()[0]
        if n:
            raise RuntimeError(f"liveness_attempts holds {n} verified consent attempt(s); refusing to drop their evidence "
                               "(restore a backup instead)")
    conn.execute("DROP INDEX IF EXISTS liveness_by_status")
    for name, _ in reversed(COLUMNS):
        drop_column(conn, "liveness_attempts", name)
