"""`python -m evals clips|run|compare` (from backend/).

    python -m evals clips                         # rebuild the clips (macOS `say`)
    python -m evals run --base http://127.0.0.1:8101 --db <copy>/ave.db --log <backend log> \\
        --label baseline --budget 2.00 [--only one_line_fix question]
    python -m evals compare results/a.json results/b.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clips", help="rebuild the eval clips")
    r = sub.add_parser("run", help="run the scenarios against a backend")
    r.add_argument("--base", default="http://127.0.0.1:8101")
    r.add_argument("--db", required=True, help="the database the backend runs on (a copy)")
    r.add_argument("--log", required=True, help="the backend's log file (INFO)")
    r.add_argument("--label", default="")
    r.add_argument("--only", nargs="*")
    r.add_argument("--cap", type=float, default=1.00, help="each turn's cap, USD")
    r.add_argument("--budget", type=float, required=True, help="stop before a scenario that could pass this, USD")
    c = sub.add_parser("compare", help="before and after, per scenario")
    c.add_argument("a")
    c.add_argument("b")
    args = ap.parse_args()
    if args.cmd == "clips":
        from evals.clips import build
        for p in build():
            print(p)
        return 0
    if args.cmd == "compare":
        from evals.compare import main as compare
        return compare(args.a, args.b)
    from evals.runner import run
    run(args.base, Path(args.db), Path(args.log), args.label, args.only, args.cap, args.budget)
    return 0


if __name__ == "__main__":
    sys.exit(main())
