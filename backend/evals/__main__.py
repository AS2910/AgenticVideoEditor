"""`python -m evals clips|run|compare` (from backend/).

    python -m evals clips                         # rebuild the clips (macOS `say`)
    python -m evals run --base http://127.0.0.1:8101 --db <copy>/ave.db --log <backend log> \\
        --label baseline --budget 2.00 [--only one_line_fix question] [--runs 3]
    python -m evals compare results/a.json results/b.json
    python -m evals voice-tone --clip <video> --transcript <words.json> --voice <clone id> \\
        [--stems <dir>] [--only 1 3] --budget-chars 2000     # run 5 item 7, real speech only
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
    r.add_argument("--runs", type=int, default=3, help="runs of each scenario (mean and spread are reported)")
    r.add_argument("--budget", type=float, required=True, help="stop before a scenario that could pass this, USD")
    c = sub.add_parser("compare", help="before and after, per scenario")
    c.add_argument("a")
    c.add_argument("b")
    v = sub.add_parser("voice-tone", help="the same lines voiced the old way and the new way (run 5 item 7)")
    v.add_argument("--clip", required=True)
    v.add_argument("--transcript", required=True, help='JSON with {"words": [{text, start, end, speaker}]}')
    v.add_argument("--voice", required=True, help="the speaker's clone voice id")
    v.add_argument("--stems", help="a folder with vocals.wav and accompaniment.wav of the clip")
    v.add_argument("--only", nargs="*", type=int)
    v.add_argument("--budget-chars", type=int, required=True, help="characters each method may bill per line")
    v.add_argument("--label", default="")
    v.add_argument("--methods", nargs="*", default=["old", "new"], help="old new noref noroom")
    args = ap.parse_args()
    if args.cmd == "clips":
        from evals.clips import build
        for p in build():
            print(p)
        return 0
    if args.cmd == "voice-tone":
        from evals.voice_tone import run as voice_tone
        voice_tone(Path(args.clip), Path(args.transcript), args.voice, Path(args.stems) if args.stems else None,
                   args.only, args.budget_chars, args.label, tuple(args.methods))
        return 0
    if args.cmd == "compare":
        from evals.compare import main as compare
        return compare(args.a, args.b)
    from evals.runner import run
    run(args.base, Path(args.db), Path(args.log), args.label, args.only, args.cap, args.budget, runs_each=args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
