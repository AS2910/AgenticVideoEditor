"""The bench (Phase 19): a labelled corpus of edits, every metric computed on
each, a gate that fails the build when any gets worse, and the table the fit
ladder reads to choose its rung by predicted score.

    python -m app.bench run      # measure the corpus, write results + rungs
    python -m app.bench gate     # compare with the baseline; non-zero on a regression
    python -m app.bench accept   # make the latest results the baseline
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
BENCH_DIR = BACKEND / "bench"
RESULTS_DIR = BENCH_DIR / "results"
BASELINE = BENCH_DIR / "baseline.json"
RUNGS = BENCH_DIR / "rungs.json"
CLIPS_DIR = BENCH_DIR / "clips"
