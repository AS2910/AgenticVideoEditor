"""Voice consent V1 step 4: the line checks' acceptance eval (real spend; run by hand only).

    ANTHROPIC_API_KEY=... python -m evals.line_checks [--runs 3] [--mode line|batch|both] [--budget 1.50] [--label x]

Reads `lines.json` (50 block lines across the five block categories in English,
Hindi and Hinglish; 100 ordinary ad lines), runs the real checker
(app.safety.line_checks: the rules, then Haiku 5.5 on what they pass) over
every line, and reports per run and as mean and spread over the runs:

    blocks caught     block lines whose verdict is block (target: all 50)
    false blocks      ordinary lines whose verdict is block (target: under 5%)
    model latency     p50 and p95 of each model call, seconds (target: under 1.5 s)
    cost per line     the model's spend over every line checked, USD (target: under $0.001)

`line` mode checks each line on its own (one call per line the rules pass, the
slowest path: a single take); `batch` mode checks each group of ten lines in one
call (a Go on a plan, a batch, a language version). Every call is written to a
ledger as it is paid; the eval stops before a call once `--budget` is spent.
Results go to evals/results/<UTC time>-line-checks[-label].json.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"


class Budget:
    def __init__(self, limit: float, ledger: Path) -> None:
        self.limit, self.spent, self.ledger = limit, 0.0, ledger

    def charge(self, what: str, model: str, tokens_in: int, tokens_out: int, seconds: float) -> None:
        from app.usage import claude_usd
        usd = claude_usd(model, tokens_in, tokens_out)
        self.spent += usd
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "what": what, "model": model, "in": tokens_in,
                                "out": tokens_out, "usd": round(usd, 7), "seconds": round(seconds, 3),
                                "total_usd": round(self.spent, 6)}) + "\n")

    def left(self) -> bool:
        return self.spent < self.limit


class Timed:
    """The real reader, timing and charging every call."""

    def __init__(self, reader, budget: Budget, label: str) -> None:
        self.reader, self.budget, self.label, self.model = reader, budget, label, reader.model
        self.seconds: list[float] = []
        self.usd = 0.0

    def read(self, lines, context=None, meter=None):
        if not self.budget.left():
            raise RuntimeError("budget spent")
        got = {}

        def metered(model, tokens_in, tokens_out, *rest):
            got.update(tokens_in=tokens_in, tokens_out=tokens_out)
        t0 = time.perf_counter()
        out = self.reader.read(lines, context, meter=metered)
        took = time.perf_counter() - t0
        self.seconds.append(took)
        before = self.budget.spent
        self.budget.charge(f"{self.label} {len(lines)} line(s)", self.model, got.get("tokens_in", 0), got.get("tokens_out", 0), took)
        self.usd += self.budget.spent - before
        return out


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(len(xs) - 1, int(k) + 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def one_run(data: dict, mode: str, budget: Budget, n: int) -> dict:
    from app.adapters.claude_lines import ClaudeLineReader
    from app.safety.line_checks import LineChecks, _hash
    from app.safety import line_rules
    reader = Timed(ClaudeLineReader(os.environ["ANTHROPIC_API_KEY"], os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
                                    model="claude-haiku-5-5"), budget, f"run {n} {mode}")
    context = {"brief": "Short social ads for small Indian businesses: cafes, shops, apps, services.", "neighbours": []}
    checks = LineChecks(reader, context=lambda video_id: context)
    rows = [{"set": "block", **x} for x in data["block"]] + [{"set": "ordinary", **x} for x in data["ordinary"]]
    rule_ms = []
    for r in rows:
        t0 = time.perf_counter()
        line_rules.check(r["text"])
        rule_ms.append((time.perf_counter() - t0) * 1000)
    if mode == "batch":
        groups = [rows[i:i + 10] for i in range(0, len(rows), 10)]
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda g: checks.prepare("eval", f"v{n}-{groups.index(g)}", [x["text"] for x in g]), groups))
        verdicts = [checks.check(r["text"], owner="eval", video_id=f"v{n}-{i // 10}", voice_id=None) for i, r in enumerate(rows)]
    else:
        with ThreadPoolExecutor(4) as pool:
            verdicts = list(pool.map(lambda ir: checks.check(ir[1]["text"], owner="eval", video_id=f"v{n}-{ir[0]}", voice_id=None),
                                     enumerate(rows)))
    out = []
    for r, v in zip(rows, verdicts):
        out.append({"id": r["id"], "set": r["set"], "lang": r["lang"], "category": r.get("category"), "verdict": v.verdict,
                    "categories": list(v.categories), "by": "rules" if v.model == line_rules.VERSION else "model",
                    "failed": v.model_failed, "reason": v.reason})
    block = [o for o in out if o["set"] == "block"]
    ordinary = [o for o in out if o["set"] == "ordinary"]
    return {
        "run": n, "mode": mode,
        "blocks_caught": sum(o["verdict"] == "block" for o in block), "block_lines": len(block),
        "blocks_held": sum(o["verdict"] == "review" for o in block),
        "blocks_by_rules": sum(o["verdict"] == "block" and o["by"] == "rules" for o in block),
        "false_blocks": sum(o["verdict"] == "block" for o in ordinary), "ordinary_lines": len(ordinary),
        "ordinary_held": sum(o["verdict"] == "review" for o in ordinary),
        "model_failures": sum(o["failed"] for o in out),
        "model_calls": len(reader.seconds), "latency_p50_s": _pct(reader.seconds, 0.5), "latency_p95_s": _pct(reader.seconds, 0.95),
        "rules_ms_max": max(rule_ms), "rules_ms_mean": statistics.mean(rule_ms),
        "model_usd": reader.usd, "usd_per_line": reader.usd / len(rows),
        "missed": [o for o in block if o["verdict"] != "block"],
        "false": [o for o in ordinary if o["verdict"] != "pass"],
    }


def summary(runs: list[dict]) -> dict:
    keys = ("blocks_caught", "blocks_held", "blocks_by_rules", "false_blocks", "ordinary_held", "latency_p50_s", "latency_p95_s",
            "usd_per_line", "rules_ms_max", "model_calls")
    out = {}
    for k in keys:
        xs = [r[k] for r in runs if r[k] is not None]
        out[k] = {"mean": statistics.mean(xs) if xs else None, "min": min(xs) if xs else None, "max": max(xs) if xs else None,
                  "stdev": statistics.pstdev(xs) if len(xs) > 1 else 0.0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.line_checks", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--mode", choices=("line", "batch", "both"), default="both")
    ap.add_argument("--budget", type=float, default=1.50)
    ap.add_argument("--spent", type=float, default=0.0, help="already spent by earlier runs of this eval, USD")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY (this eval spends real money).", file=sys.stderr)
        return 2
    data = json.loads((HERE / "lines.json").read_text(encoding="utf-8"))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-line-checks" + (f"-{args.label}" if args.label else "")
    budget = Budget(args.budget, RESULTS / f"{name}.ledger.jsonl")
    budget.spent = args.spent
    modes = ("line", "batch") if args.mode == "both" else (args.mode,)
    runs = []
    for mode in modes:
        for n in range(1, args.runs + 1):
            if not budget.left():
                print(f"budget reached (${budget.spent:.4f}); stopping", file=sys.stderr)
                break
            r = one_run(data, mode, budget, n)
            runs.append(r)
            print(f"{mode} run {n}: caught {r['blocks_caught']}/{r['block_lines']} (rules {r['blocks_by_rules']}), "
                  f"false blocks {r['false_blocks']}/{r['ordinary_lines']}, held ordinary {r['ordinary_held']}, "
                  f"p50 {r['latency_p50_s']:.2f} s p95 {r['latency_p95_s']:.2f} s, ${r['usd_per_line']:.6f}/line, "
                  f"failures {r['model_failures']}, total ${budget.spent:.4f}")
    from app.adapters.claude_lines import PROMPT_VERSION
    from app.safety.line_rules import VERSION
    result = {"label": args.label, "rules": VERSION, "prompt": PROMPT_VERSION, "model": "claude-haiku-5-5",
              "spent_usd": budget.spent, "runs": runs,
              "summary": {m: summary([r for r in runs if r["mode"] == m]) for m in modes}}
    (RESULTS / f"{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"spent ${budget.spent:.4f}; results in {RESULTS / (name + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
