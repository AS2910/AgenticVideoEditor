"""Run 5 item 6: how long a small line edit takes, Enter to a proposal ready to
hear, the fast path against the full turn, through the app's own endpoints.

Usage (from backend/, PYTHONPATH=.):
  python ../tools/load/fastpath_bench.py <workdir> [runs]
Every vendor is the launch rehearsal's timed mock (AVE_MOCK_VENDORS=1), with the
latencies LOAD.md's load test used unless set: Claude 1 to 3 s a call
(AVE_MOCK_CLAUDE_SECONDS), a voiced line 2 to 6 s (AVE_MOCK_SYNTH_SECONDS), a
render 5 to 20 s (AVE_MOCK_RENDER_SECONDS). Nothing leaves the machine; no spend.

The clip is the bundled sample (one line, "Get 20% off today only.", 2.3 s).
The edit changes 4 words of it. Fast: POST /videos/{id}/lines/quick, timed to
the take standing on the line, ready to hear. Full: the same sentence as a turn
(POST /turns), timed to its take being ready to hear (the mock planner makes a
take in its first call) and to the turn's end (closing call and preview render).
Results: docs/rehearsal/load/fastpath-results.json, and DECISIONS.md / MORNING.md.
"""
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

work = Path(sys.argv[1])
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 20
work.mkdir(parents=True, exist_ok=True)
for k in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY", "AVE_DRY_RUN", "DATABASE_URL", "AVE_CHAOS"):
    os.environ[k] = ""
os.environ["AVE_MOCK_VENDORS"] = "1"
os.environ["AVE_DATA_DIR"] = str(work / "data")
# 48 takes and 24 planner turns on one video: past the default voice allowance and video ceiling.
os.environ.setdefault("AVE_VOICE_BUDGET_CHARS", "100000")
os.environ.setdefault("AVE_PROJECT_BUDGET_USD", "100")
os.environ.setdefault("AVE_USER_BUDGET_USD", "100")
os.environ.setdefault("AVE_MOCK_CLAUDE_SECONDS", "1-3")
os.environ.setdefault("AVE_MOCK_SYNTH_SECONDS", "2-6")
os.environ.setdefault("AVE_MOCK_RENDER_SECONDS", "5-20")

from fastapi.testclient import TestClient  # noqa: E402

import app.api.main as main  # noqa: E402

LINE = "Get 20% off today only."
EDITS = ("Save 30% on weekends only.", "Save 40% on weekends only.")     # 4 words changed, each
SENTENCE = "Replace the line at 0:00 (“Get 20% off today only.”) with “{}”"
src = Path(main.__file__).resolve().parents[1] / "tutorial" / "fixture" / "sample-ad.mp4"
client = TestClient(main.app)
with open(src, "rb") as fh:
    r = client.post("/videos", files={"file": (src.name, fh, "video/mp4")}, data={"consent": "true"})
assert r.status_code == 200, r.text
vid = r.json()["video_id"]
assert [s["text"] for s in r.json().get("statements", [])] in ([LINE], []), r.json().get("statements")


def ready_candidates() -> set[str]:
    plan = main.repo.latest_plan(vid)
    return {i.candidate_id for i in (plan.items if plan else ()) if i.status == "ready" and i.candidate_id}


def wait_job(job_id: str, seen: set[str], t0: float) -> tuple[float | None, float, dict]:
    """(seconds to a new take ready to hear, seconds to the job's end, its result)."""
    first = None
    while True:
        if first is None and ready_candidates() - seen:
            first = time.monotonic() - t0
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            if first is None and ready_candidates() - seen:
                first = time.monotonic() - t0
            return first, time.monotonic() - t0, job
        time.sleep(0.02)


def run(kind: str, n: int) -> list[dict]:
    out = []
    for k in range(n):
        text = EDITS[k % 2]
        seen = ready_candidates()
        t0 = time.monotonic()
        if kind == "fast":
            resp = client.post(f"/videos/{vid}/lines/quick", json={"start": 0.0, "end": 2.3, "text": text, "before": LINE,
                                                                   "turn_text": SENTENCE.format(text)})
            assert resp.status_code == 202 and resp.json()["route"] == "fast", resp.text
        else:
            resp = client.post(f"/videos/{vid}/turns", json={"text": SENTENCE.format(text)})
            assert resp.status_code == 202, resp.text
        ready, done, job = wait_job(resp.json()["job_id"], seen, t0)
        assert job["status"] == "succeeded" and ready is not None, job
        out.append({"ready_s": round(ready, 3), "done_s": round(done, 3)})
        print(f"{kind} {k + 1}/{n}: ready {ready:.2f} s, done {done:.2f} s", flush=True)
    return out


def pct(values: list[float], p: float) -> float:
    xs = sorted(values)
    return round(xs[min(len(xs) - 1, max(0, math.ceil(p / 100 * len(xs)) - 1))], 2)   # nearest rank


fast = run("fast", runs)
full = run("full", runs)
summary = {
    "latencies": {k: os.environ[k] for k in ("AVE_MOCK_CLAUDE_SECONDS", "AVE_MOCK_SYNTH_SECONDS", "AVE_MOCK_RENDER_SECONDS")},
    "runs": runs,
    "fast": {"p50_ready": pct([r["ready_s"] for r in fast], 50), "p95_ready": pct([r["ready_s"] for r in fast], 95),
             "mean_ready": round(statistics.mean(r["ready_s"] for r in fast), 2), "samples": fast},
    "full": {"p50_ready": pct([r["ready_s"] for r in full], 50), "p95_ready": pct([r["ready_s"] for r in full], 95),
             "p50_done": pct([r["done_s"] for r in full], 50), "p95_done": pct([r["done_s"] for r in full], 95),
             "mean_ready": round(statistics.mean(r["ready_s"] for r in full), 2), "samples": full},
}
print(json.dumps({k: (v if k in ("latencies", "runs") else {m: x for m, x in v.items() if m != "samples"})
                  for k, v in summary.items()}, indent=2))
out = Path(os.environ.get("FASTPATH_RESULTS", work / "fastpath-results.json"))
out.write_text(json.dumps(summary, indent=2) + "\n")
print(f"written to {out}")
