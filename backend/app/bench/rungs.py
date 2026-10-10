"""The rungs table: what each rung of the fit ladder scored, per ratio band
(Phase 19). `fit.ladder()` reads it to put the better rung first."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from app.bench.runner import Result
from app.media.fit import band

# A case's rung is the rungs it used, joined with "+"; each is evidence for that rung.
RUNGS = ("gaps", "flex", "tempo")


def rungs_used(rung: str) -> list[str]:
    return [r for r in rung.split("+") if r in RUNGS]


def build(results: Sequence[Result]) -> dict:
    """{band: {rung: {"n", "score"}}} from the cases that were fitted; a case
    that reached a rung is evidence for it, pass or fail."""
    sums: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        for rung in rungs_used(r.rung):
            sums[band(r.ratio)][rung].append(r.score)
    return {
        "bands": {
            b: {rung: {"n": len(v), "score": round(sum(v) / len(v), 4)} for rung, v in rungs.items()}
            for b, rungs in sums.items()
        }
    }


def save(results: Sequence[Result], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(results), indent=2) + "\n")
    return path
