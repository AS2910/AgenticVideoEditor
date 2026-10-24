"""Before and after, per scenario: the turn's cost and every score, with the
change, and a flag on any score more than 5% worse.

Costs are compared warm: a run's first request finds the shared prefix (the
tools and the system prompt, the same for every turn of every user) cold or
warm depending only on what ran in the five minutes before it. A request that
wrote that whole prefix is counted as having read it, at the ledger's rates
(the planner's fallback $5 a million, writes 1.25x, reads 0.1x); the raw
ledger figure is printed beside it."""
from __future__ import annotations

import json
from pathlib import Path

# score: (higher is better, the smallest change that counts as one)
SCORES = {"wer": (False, 0.02), "wer_vs_asked": (False, 0.02), "sim_o": (True, 0.01), "utmos": (True, 0.05),
          "duration_error_s": (False, 0.05), "plan_quality": (True, 0.0)}
WORSE_BY = 0.05


PLANNER_USD_PER_TOKEN = 5.00 / 1_000_000
WRITE, READ = 1.25, 0.10


def shared_prefix(runs: dict[str, dict]) -> int:
    """What a warm first request read in this run (0 when every one was cold)."""
    return max((r["requests"][0]["cache_read"] for r in runs.values() if r.get("requests")), default=0)


def load(path: str | Path, static: int | None = None) -> dict[str, dict]:
    """The run's scenarios with `warm_usd`. `static` is the shared prefix's
    size when this run never found it warm (taken from the run it is compared with)."""
    data = json.loads(Path(path).read_text())
    runs = {r["scenario"]: r for r in data["runs"] if r.get("status") != "error"}
    static = shared_prefix(runs) or static or 0
    for r in runs.values():
        cold = sum(static for q in r.get("requests") or () if q["cache_read"] == 0 and static and q["cache_write"] >= static)
        r["cost"]["warm_usd"] = round(r["cost"]["turn_usd"] - cold * PLANNER_USD_PER_TOKEN * (WRITE - READ), 5)
    return runs


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
    a, b = load(a_path, shared_prefix(b)), load(b_path, shared_prefix(a))
    rows = ["| scenario | turn $ before | turn $ after | change | raw ledger before / after | " + " | ".join(SCORES) + " |",
            "|---|---|---|---|---|" + "---|" * len(SCORES)]
    flags, costs_a, costs_b = [], [], []
    for name in [n for n in a if n in b]:
        ra, rb = a[name], b[name]
        ca, cb = ra["cost"]["warm_usd"], rb["cost"]["warm_usd"]
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
        raw = f"${ra['cost']['turn_usd']:.4f} / ${rb['cost']['turn_usd']:.4f}"
        rows.append(f"| {name} | ${ca:.4f} | ${cb:.4f} | {change} | {raw} | " + " | ".join(cells) + " |")
    if costs_a:
        ma, mb = sum(costs_a) / len(costs_a), sum(costs_b) / len(costs_b)
        rows.append(f"\nAverage turn: ${ma:.4f} -> ${mb:.4f} ({(mb - ma) / ma * 100:+.0f}%) over {len(costs_a)} scenarios")
    return "\n".join(rows), flags


def main(a: str, b: str) -> int:
    text, flags = table(a, b)
    print(text)
    print("\nScores more than 5% worse: " + ("; ".join(flags) if flags else "none"))
    return 1 if flags else 0
