"""Run 4, item 3b: one real 60 s render through the app's own render path
(main._export -> _render_now -> render + compose), 3 runs.

Usage (from backend/, PYTHONPATH=.):
  python ../tools/load/render_bench.py <source.mp4> <transcript.json> <workdir> [runs]
The source is an 8 s phone clip looped to 60 s and scaled to 1080x1920; the
transcript is that clip's own words (its `videos.transcript`), tiled every 8 s.
Every vendor key is blanked first, so the mock voice makes the takes: no spend.
Results: LOAD.md, "One real 60 s render"; docs/rehearsal/load/render60-results.json.
"""
import json
import os
import resource
import sys
import time
from pathlib import Path

src, transcript_path, work = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
runs = int(sys.argv[4]) if len(sys.argv) > 4 else 3
work.mkdir(parents=True, exist_ok=True)
for k in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY", "AVE_DRY_RUN", "DATABASE_URL", "AVE_MOCK_VENDORS"):
    os.environ[k] = ""
os.environ["AVE_DATA_DIR"] = str(work / "data")

from fastapi.testclient import TestClient  # noqa: E402

import app.api.main as main  # noqa: E402
from app.domain.models import Selection, Transcript, Word  # noqa: E402

client = TestClient(main.app)
with open(src, "rb") as fh:
    r = client.post("/videos", files={"file": (src.name, fh, "video/mp4")}, data={"consent": "true"})
assert r.status_code == 200, r.text
vid = r.json()["video_id"]

# The clip's real words (a phone clip with speech), tiled over the 60 s the clip loops to.
raw = json.loads(transcript_path.read_text())["words"]
period = 7.999875
words, k = [], 0
while True:
    off = k * period
    if off >= 60:
        break
    for w in raw:
        if w["start"] + off < 60 - 0.05:
            words.append(Word(text=w["text"], start=round(w["start"] + off, 3), end=round(min(w["end"] + off, 59.95), 3),
                              speaker=w.get("speaker")))
    k += 1
main.repo.update_transcript(vid, Transcript(words=tuple(words)))
record = main.repo.get(vid)

# A realistic edit set: four replaced lines (one per loop, a few words each) and a layered voice-over.
def line(n):
    ws = [w for w in words if n * period <= w.start < n * period + 3.0][:6]
    return Selection(ws[0].start, ws[-1].end), " ".join(w.text for w in ws)

edits = []
for n, text in ((0, "excuse me for not drinking"), (2, "why am I not drinking now"), (4, "sorry, I am not drinking"), (6, "excuse me, not tonight")):
    sel, old = line(n)
    for fit in ("fit", None):
        try:
            c = main._generate(vid, main.repo.get(vid), main.repo.next_candidate_id(vid), sel, text, "mock", fit, "replace",
                               lambda p, s: None)
            break
        except Exception as exc:  # noqa: BLE001
            print("retry without fit:", exc)
    edits.append(main._approve_candidate(vid, c, not c.continuity.passed))
    print(f"replace {sel.start:.2f}-{sel.end:.2f}: {old!r} -> {text!r}")
vo = main._generate(vid, main.repo.get(vid), main.repo.next_candidate_id(vid), Selection(30.0, 38.0),
                    "And that is the whole story of the evening, told in one breath.", "mock", None, "layer", lambda p, s: None)
edits.append(main._approve_candidate(vid, vo, not vo.continuity.passed))
print("layered voice-over 30.0-38.0, edits:", edits)


def rusage():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime, c.ru_utime + c.ru_stime, c.ru_maxrss, s.ru_maxrss


import subprocess  # noqa: E402
import threading  # noqa: E402


def tree_rss_mb() -> float:
    """This process and every descendant (the ffmpeg runs), RSS summed, from ps."""
    kids, rss = {}, {}
    if os.path.isdir("/proc/self"):            # Linux (the api image has no ps)
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                fields = dict(line.split(":", 1) for line in open(f"/proc/{d}/status").read().splitlines() if ":" in line)
            except OSError:
                continue
            pid, ppid = int(d), int(fields["PPid"].strip())
            kids.setdefault(ppid, []).append(pid)
            rss[pid] = int(fields.get("VmRSS", "0 kB").split()[0])
        rows = []
    else:
        rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout.split("\n")
    for row in rows:
        parts = row.split()
        if len(parts) == 3:
            pid, ppid, kb = map(int, parts)
            kids.setdefault(ppid, []).append(pid)
            rss[pid] = kb
    total, todo = 0, [os.getpid()]
    while todo:
        pid = todo.pop()
        total += rss.get(pid, 0)
        todo.extend(kids.get(pid, []))
    return total / 1024


def sampled(work):
    peak, stop = [0.0], threading.Event()

    def watch():
        while not stop.is_set():
            peak[0] = max(peak[0], tree_rss_mb())
            stop.wait(0.2)
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        return work(), peak
    finally:
        stop.set()
        t.join()


results = []
for i in range(runs):
    main.repo.set_settings(vid, renders={})          # no reuse: every run renders from scratch
    a_self, a_kids, _, _ = rusage()
    t0 = time.time()
    out, peak = sampled(lambda: main._export(main.repo.get(vid)))
    wall = time.time() - t0
    b_self, b_kids, kids_rss, self_rss = rusage()
    cpu = (b_self - a_self) + (b_kids - a_kids)
    res = {"run": i + 1, "wall_s": round(wall, 2), "cpu_s": round(cpu, 2), "cpu_ffmpeg_s": round(b_kids - a_kids, 2),
           "cores_busy": round(cpu / wall, 2), "peak_tree_rss_mb": round(peak[0], 1),
           "load_avg": os.getloadavg()[0], "cached": out["cached"],
           "duration": out["render"]["duration"],
           "pieces": sorted({p["kind"] for p in out["pieces"]}) if out.get("pieces") else None}
    print(json.dumps(res))
    results.append(res)
(work / "results.json").write_text(json.dumps(results, indent=2))
