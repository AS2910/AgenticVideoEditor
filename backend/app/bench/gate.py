"""The gate: what a change may not make worse (Phase 19).

Two kinds of rule. The *labels* are absolute: every good edit passes, every
bad one fails, every take that cannot fit is asked about. The *baseline* is
relative: no case's scores may fall, and no seam, no frozen frame, may grow,
beyond a small tolerance, from the last accepted run.
"""
from __future__ import annotations

from typing import Sequence

from app.bench.runner import Result

SCORE_TOLERANCE = 0.02      # a continuity score may not fall by more than this
SEAM_DB_TOLERANCE = 1.0     # a seam may not get louder than this, in dB
SEAM_ST_TOLERANCE = 1.0     # ...or change colour by more than this, in semitones
FROZEN_TOLERANCE = 0.01     # a frozen frame may not grow at all


def check(results: Sequence[Result], baseline: Sequence[Result] | None = None) -> list[str]:
    """Every rule that fails, as a sentence. Empty means the gate is open."""
    failures: list[str] = []
    for r in results:
        if not r.ok:
            what = ("should have passed" if r.label == "good" else "should have failed"
                    if r.label == "bad" else "should have been asked about")
            got = "asked about" if r.rung == "ask" else "passed" if r.passed else "failed"
            failures.append(f"{r.name}: {what}, but was {got}" + (f" ({'; '.join(r.warnings)})" if r.warnings else ""))
    if not baseline:
        return failures
    before = {b.name: b for b in baseline}
    for r in results:
        b = before.get(r.name)
        if b is None:
            continue
        for key, tol, lower_is_better in (
            ("prosody", SCORE_TOLERANCE, False), ("audio_integration", SCORE_TOLERANCE, False),
            ("seam_level_db", SEAM_DB_TOLERANCE, True), ("seam_colour_st", SEAM_ST_TOLERANCE, True),
            ("frozen_seconds", FROZEN_TOLERANCE, True),
        ):
            now, was = getattr(r, key), getattr(b, key)
            if now is None or was is None:
                continue
            worse = now > was + tol if lower_is_better else now < was - tol
            if worse:
                failures.append(f"{r.name}: {key} {was:.3f} → {now:.3f}")
    return failures
