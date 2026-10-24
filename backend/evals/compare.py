"""Before and after, per scenario: the turn's cost and every score, with the
change, and a flag on any score more than 5% worse."""
from __future__ import annotations

import json
from pathlib import Path

# score: (higher is better, the smallest change that counts as one)
SCORES = {"wer": (False, 0.02), "wer_vs_asked": (False, 0.02), "sim_o": (True, 0.01), "utmos": (True, 0.05),
          "duration_error_s": (False, 0.05), "plan_quality": (True, 0.0)}
WORSE_BY = 0.05


def load(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text())
    return {r["scenario"]: r for r in data["runs"] if r.get("status") != "error"}


def worse(name: str, a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    higher, floor = SCORES[name]
    delta = (a - b) if higher else (b - a)
    return delta > floor and delta > WORSE_BY * max(abs(a), 1e-9)


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def table(a_path: str | Path, b_path: str | Path) -> tuple[str, list[str]]:
    a, b = load(a_path), load(b_path)
    rows = ["| scenario | turn $ before | turn $ after | change | " + " | ".join(SCORES) + " |",
            "|---|---|---|---|" + "---|" * len(SCORES)]
    flags, costs_a, costs_b = [], [], []
    for name in [n for n in a if n in b]:
        ra, rb = a[name], b[name]
        ca, cb = ra["cost"]["turn_usd"], rb["cost"]["turn_usd"]
        costs_a.append(ca)
        costs_b.append(cb)
        cells = []
        for s in SCORES:
            va, vb = ra["scores"].get(s), rb["scores"].get(s)
            bad = worse(s, va, vb)
            if bad:
                flags.append(f"{name}: {s} {_fmt(va)} -> {_fmt(vb)}")
            cells.append(f"{_fmt(va)} -> {_fmt(vb)}" + (" WORSE" if bad else ""))
        change = f"{(cb - ca) / ca * 100:+.0f}%" if ca else "n/a"
        rows.append(f"| {name} | ${ca:.4f} | ${cb:.4f} | {change} | " + " | ".join(cells) + " |")
    if costs_a:
        ma, mb = sum(costs_a) / len(costs_a), sum(costs_b) / len(costs_b)
        rows.append(f"\nAverage turn: ${ma:.4f} -> ${mb:.4f} ({(mb - ma) / ma * 100:+.0f}%) over {len(costs_a)} scenarios")
    return "\n".join(rows), flags


def main(a: str, b: str) -> int:
    text, flags = table(a, b)
    print(text)
    print("\nScores more than 5% worse: " + ("; ".join(flags) if flags else "none"))
    return 1 if flags else 0
