"""`python -m evals.messy build|run` (from backend/). See evals/messy/__init__.py."""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.messy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="make the variants")
    b.add_argument("--only", nargs="*")
    r = sub.add_parser("run", help="score the variants")
    r.add_argument("--label", default="")
    r.add_argument("--only", nargs="*")
    r.add_argument("--budget", type=float, default=0.50, help="stop paying for transcription past this, USD")
    r.add_argument("--no-voice", action="store_true", help="no paid ElevenLabs take")
    r.add_argument("--no-bed", action="store_true", help="skip the separation and bed measure")
    r.add_argument("--vocals", action="store_true", help="transcribe the separated voice when a bed is found")
    rep = sub.add_parser("report", help="the breakage table of a result, as Markdown")
    rep.add_argument("result")
    rep.add_argument("--before")
    args = ap.parse_args()
    if args.cmd == "build":
        from evals.messy.variants import build
        for p in build(args.only):
            print(p)
        return 0
    if args.cmd == "report":
        from evals.messy.report import main as report
        print(report(args.result, args.before))
        return 0
    from evals.messy.runner import run
    print(run(args.label, args.only, budget=args.budget, voice=not args.no_voice, bed=not args.no_bed,
              transcribe_vocals=args.vocals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
