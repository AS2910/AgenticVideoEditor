"""`python -m app.bench run|gate|accept`."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.bench import BASELINE, CLIPS_DIR, RESULTS_DIR, RUNGS, corpus, gate, rungs
from app.bench.runner import from_json, run, save, table
from app.media import ffmpeg


def _latest(results_dir: Path) -> Path | None:
    files = sorted(results_dir.glob("*.json"))
    return files[-1] if files else None


def _run(args) -> int:
    if not ffmpeg.available():
        print("ffmpeg is needed to run the bench.", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="ave-bench-"))
    try:
        cases = corpus.build(work, Path(args.clips) if args.clips else CLIPS_DIR)
        results = run(cases, work)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = Path(args.out) if args.out else RESULTS_DIR / f"{stamp}.json"
    save(results, out)
    rungs.save(results, Path(args.rungs) if args.rungs else RUNGS)
    print(table(results))
    met = sum(r.ok for r in results)
    print(f"\n{met} of {len(results)} expectations met · written {out}")
    return 0 if met == len(results) else 1


def _gate(args) -> int:
    results_path = Path(args.results) if args.results else None
    if results_path is None:
        code = _run(args)
        results_path = Path(args.out) if args.out else _latest(RESULTS_DIR)
        if results_path is None:
            return code
    results = from_json(json.loads(results_path.read_text()))
    baseline_path = Path(args.baseline) if args.baseline else BASELINE
    baseline = from_json(json.loads(baseline_path.read_text())) if baseline_path.exists() else None
    failures = gate.check(results, baseline)
    if failures:
        print("\nThe gate is closed:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"\nThe gate is open: {len(results)} cases, "
          + ("no regression against the baseline." if baseline else "no baseline yet (run `accept` to set one)."))
    return 0


def _accept(args) -> int:
    results_path = Path(args.results) if args.results else _latest(RESULTS_DIR)
    if results_path is None:
        code = _run(args)
        if code:
            return code
        results_path = _latest(RESULTS_DIR)
    baseline_path = Path(args.baseline) if args.baseline else BASELINE
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(results_path, baseline_path)
    print(f"Baseline is now {results_path.name} → {baseline_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.bench", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", _run), ("gate", _gate), ("accept", _accept)):
        sp = sub.add_parser(name)
        sp.add_argument("--out", help="where to write the results JSON")
        sp.add_argument("--results", help="an existing results JSON to gate or accept")
        sp.add_argument("--baseline", help="the baseline JSON (default bench/baseline.json)")
        sp.add_argument("--rungs", help="where to write the rungs table (default bench/rungs.json)")
        sp.add_argument("--clips", help="a folder of real clips with manifests (default bench/clips)")
        sp.add_argument("--keep", action="store_true", help="keep the working directory")
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
