"""Before and after, per scenario: the turn's cost and every score, with the
change, and a flag on any score more than 5% worse. Each side is the mean
of its runs with their spread (lowest to highest); a score is flagged only when
its mean is more than 5% worse and outside the other side's spread.

Costs are compared warm: a run's first request finds the shared prefix (the
tools and the system prompt, the same for every turn of every user) cold or
warm depending only on what ran in the five minutes before it. A request that
wrote that whole prefix is counted as having read it, at the ledger's rates
(the planner's fallback $5 a million, writes 1.25x, reads 0.1x); the raw
ledger figures are in the JSON."""
from __future__ import annotations

import json
from pathlib import Path

# score: (higher is better, the smallest change that counts as one)
SCORES = {"wer": (False, 0.02), "wer_vs_asked": (False, 0.02), "sim_o": (True, 0.01), "utmos": (True, 0.05),
          "duration_error_s": (False, 0.05), "plan_quality": (True, 0.0)}
WORSE_BY = 0.05


PLANNER_USD_PER_TOKEN = 5.00 / 1_000_000
WRITE, READ = 1.25, 0.10


def shared_prefix(runs: dict[str, list[dict]]) -> int:
    """What a warm first request read in this file (0 when every one was cold)."""
    return max((r["requests"][0]["cache_read"] for rs in runs.values() for r in rs if r.get("requests")), default=0)


def load(path: str | Path, static: int | None = None) -> dict[str, list[dict]]:
    """Each scenario's runs, with `warm_usd`. `static` is the shared prefix's
    size when this file never found it warm (taken from the file it is compared with)."""
    data = json.loads(Path(path).read_text())
    runs: dict[str, list[dict]] = {}
    for r in data["runs"]:
        if r.get("status") != "error":
            runs.setdefault(r["scenario"], []).append(r)
    static = shared_prefix(runs) or static or 0
    for r in (r for rs in runs.values() for r in rs):
        cold = sum(static for q in r.get("requests") or () if q["cache_read"] == 0 and static and q["cache_write"] >= static)
        r["cost"]["warm_usd"] = round(r["cost"]["turn_usd"] - cold * PLANNER_USD_PER_TOKEN * (WRITE - READ), 5)
    return runs


def spread(values) -> dict | None:
    """Mean, lowest and highest of the values that are there (None when none is)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {"mean": sum(vals) / len(vals), "min": min(vals), "max": max(vals), "n": len(vals)}


def worse(name: str, a: dict | float | None, b: dict | float | None) -> bool:
    """B is worse than A on this score: its mean is past the smallest change
    that counts, more than 5% worse, and outside A's spread (one run each is
    the old single-run rule, a spread of one point)."""
    if a is None or b is None:
        return False
    a = a if isinstance(a, dict) else {"mean": a, "min": a, "max": a}
    b = b if isinstance(b, dict) else {"mean": b, "min": b, "max": b}
    higher, floor = SCORES[name]
    delta = (a["mean"] - b["mean"]) if higher else (b["mean"] - a["mean"])
    outside = b["mean"] < a["min"] if higher else b["mean"] > a["max"]
    return delta > floor and delta > WORSE_BY * max(abs(a["mean"]), 1e-9) and outside


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, dict):
        if v["n"] == 1 or v["min"] == v["max"]:
            return _fmt(v["mean"])
        return f"{v['mean']:.3f} ({v['min']:.3f}-{v['max']:.3f})"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def table(a_path: str | Path, b_path: str | Path) -> tuple[str, list[str]]:
    a, b = load(a_path), load(b_path)
    a, b = load(a_path, shared_prefix(b)), load(b_path, shared_prefix(a))
    rows = ["| scenario | runs | turn $ before | turn $ after | change | " + " | ".join(SCORES) + " |",
            "|---|---|---|---|---|" + "---|" * len(SCORES)]
    flags, costs_a, costs_b = [], [], []
    for name in [n for n in a if n in b]:
        ra, rb = a[name], b[name]
        ca, cb = spread(r["cost"]["warm_usd"] for r in ra), spread(r["cost"]["warm_usd"] for r in rb)
        costs_a.append(ca["mean"])
        costs_b.append(cb["mean"])
        cells = []
        for s in SCORES:
            va, vb = spread(r["scores"].get(s) for r in ra), spread(r["scores"].get(s) for r in rb)
            bad = worse(s, va, vb)
            if bad:
                flags.append(f"{name}: {s} {_fmt(va)} -> {_fmt(vb)}")
            cells.append(f"{_fmt(va)} -> {_fmt(vb)}" + (" WORSE" if bad else ""))
        change = f"{(cb['mean'] - ca['mean']) / ca['mean'] * 100:+.0f}%" if ca["mean"] else "n/a"
        money = lambda c: f"${c['mean']:.4f}" + (f" (${c['min']:.4f}-${c['max']:.4f})" if c["n"] > 1 else "")  # noqa: E731
        rows.append(f"| {name} | {len(ra)} / {len(rb)} | {money(ca)} | {money(cb)} | {change} | " + " | ".join(cells) + " |")
    if costs_a:
        ma, mb = sum(costs_a) / len(costs_a), sum(costs_b) / len(costs_b)
        rows.append(f"\nAverage turn: ${ma:.4f} -> ${mb:.4f} ({(mb - ma) / ma * 100:+.0f}%) over {len(costs_a)} scenarios")
    if any(len(rs) < 3 for rs in (*a.values(), *b.values())):
        rows.append("\nFewer than 3 runs of a scenario: a single run is inside the noise (run 4), so read its flags as a hint.")
    return "\n".join(rows), flags


def main(a: str, b: str) -> int:
    text, flags = table(a, b)
    print(text)
    print("\nScores more than 5% worse, outside the spread: " + ("; ".join(flags) if flags else "none"))
    return 1 if flags else 0
