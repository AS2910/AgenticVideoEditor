"""Run the scenarios against a running backend, one fresh upload each, and
score what each turn made.

The backend must run on a database copy (its ledger is read directly, read
only) and log at INFO to a file the runner can read: the agent's own
"agent request" lines give the token profile of every request a turn made.
Every run spends real money unless the backend mocks its vendors; the
runner stops before a scenario whose estimate would pass `--budget`.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from evals import clips, metrics
from evals.scenarios import SCENARIOS, Scenario

RESULTS = Path(__file__).resolve().parent / "results"
# What one scenario has cost at most (setup and turn), from the runs so far; the budget guard uses it.
ESTIMATE_USD = {"one_line_fix": 0.20, "five_line_rewrite": 0.70, "new_voiceover": 0.35, "hinglish_line": 0.25,
                "hindi_version": 0.90, "question": 0.15}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=600.0)

    def _ok(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise RuntimeError(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def get(self, path: str) -> dict:
        return self._ok(self.http.get(self.base + path))

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._ok(self.http.post(self.base + path, json=body or {}))

    def put(self, path: str, body: dict) -> dict:
        return self._ok(self.http.put(self.base + path, json=body))

    def upload(self, path: Path) -> dict:
        with path.open("rb") as f:
            return self._ok(self.http.post(self.base + "/videos", files={"file": (path.name, f, "video/mp4")},
                                           data={"consent": "true"}))

    def wait(self, job_id: str, limit_s: float = 900.0) -> dict:
        t0 = time.time()
        while time.time() - t0 < limit_s:
            j = self.get(f"/jobs/{job_id}")
            if j["status"] in ("succeeded", "failed"):
                return j
            time.sleep(2)
        raise TimeoutError(f"job {job_id} still running after {limit_s:.0f} s")


def _lines_text(statements: list[dict]) -> str:
    return "\n".join(f"- {s['start']:.1f}–{s['end']:.1f} s: “{s['text']}”" for s in statements) or "- (no spoken lines)"


def _score_takes(sc: Scenario, items: list[dict], statements: list[dict], clip: Path, db: Path, pid: str,
                 keys: dict, work: Path) -> tuple[list[dict], float]:
    takes, scoring_usd = [], 0.0
    expected = list(sc.expect_words)
    for n, item in enumerate(i for i in items if i.get("candidate") and i.get("status") != "dismissed"):
        cand = item["candidate"]
        audio = metrics.candidate_audio(db, pid, cand["candidate_id"])
        row = {"item_id": item["item_id"], "status": item["status"], "old_text": item.get("old_text"),
               "new_text": item["new_text"], "start": item["selection"]["start"], "end": item["selection"]["end"],
               "mix": item.get("mix"), "fit_notes": cand.get("fit_notes"), "passed": (cand.get("continuity") or {}).get("passed")}
        if audio is None:
            takes.append({**row, "error": "no audio"})
            continue
        heard = None
        if keys:
            try:
                heard, usd = metrics.transcribe(audio, keys, sc.language)
                scoring_usd += usd
            except Exception as exc:  # noqa: BLE001 - a take Whisper could not hear is reported, not fatal
                row["whisper_error"] = str(exc)[:200]
        row["heard"] = heard
        row["wer"] = round(metrics.wer(item["new_text"], heard), 3) if heard is not None else None
        if heard is not None and n < len(expected):
            row["wer_vs_asked"] = round(metrics.wer(expected[n], heard), 3)
        # The speaker the take replaces, from the original clip (an added line has none).
        line = max(statements, key=lambda s: min(s["end"], row["end"]) - max(s["start"], row["start"]), default=None)
        replaces = line is not None and item.get("mix") != "layer" and min(line["end"], row["end"]) - max(line["start"], row["start"]) > 0
        ref = metrics.segment(clip, line["start"], line["end"], work / f"ref-{item['item_id']}.wav") if replaces else None
        row.update(metrics.voice_scores(audio, ref))
        span = metrics.speech_span(audio)
        if span is not None:
            spoken = span[1] - span[0]
            if replaces:
                # Against the line it replaces: the same length is the ask.
                row["duration_error_s"] = round(abs(spoken - (line["end"] - line["start"])), 3)
            else:
                # An added line may be shorter than its window, never longer.
                row["duration_error_s"] = round(max(0.0, spoken - (row["end"] - row["start"])), 3)
        takes.append(row)
    return takes, scoring_usd


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def run_one(api: Api, sc: Scenario, db: Path, log: Path, cap: float, keys: dict) -> dict:
    clip = clips.path(sc.clip)
    setup_since = _now()
    video = api.upload(clip)
    pid = video["video_id"]
    api.put(f"/videos/{pid}/settings", {"autonomy": "draft", "turn_usd": cap})
    try:
        api.post(f"/videos/{pid}/reading", {})
    except RuntimeError as exc:
        print(f"      reading failed: {exc}", flush=True)
    statements = api.get(f"/videos/{pid}")["statements"]
    text = sc.say.replace("{lines}", _lines_text(statements))
    offset = log.stat().st_size if log.exists() else 0
    turn_since = _now()
    t0 = time.time()
    job = api.post(f"/videos/{pid}/turns", {"text": text})
    job = api.wait(job["job_id"])
    seconds = round(time.time() - t0, 1)
    time.sleep(1.0)
    requests = metrics.requests_in_log(log.read_text(errors="replace")[offset:] if log.exists() else "")
    full = api.get(f"/videos/{pid}")
    result = job.get("result") or {}
    plan = result.get("plan") or full.get("plan") or {}
    items = plan.get("items") or []
    messages = api.get(f"/videos/{pid}/messages")
    work = metrics.tmpdir()
    takes, scoring_usd = _score_takes(sc, items, statements, clip, db, pid, keys, work)
    targets = range(len(statements)) if sc.targets == ("all",) else sc.targets
    quality = metrics.plan_quality(items, statements, list(targets), sc.adds, sc.question)
    setup = metrics.ledger(db, pid, setup_since)
    turn = metrics.ledger(db, pid, turn_since)
    setup_usd = round(setup["total"] - turn["total"], 5)
    steps = [m for m in messages if m.get("kind") == "step"]
    return {
        "scenario": sc.name, "video_id": pid, "status": job["status"], "error": job.get("error"), "seconds": seconds,
        "say": text, "statements": statements, "reply": result.get("reply"), "question": result.get("question"),
        "stopped": result.get("stopped"), "calls": result.get("calls"),
        "steps": [{"text": m["text"], "cost": m.get("cost"), "tool": (m.get("data") or {}).get("tool")} for m in steps],
        "takes": takes, "requests": requests,
        "scores": {
            "wer": _mean(t.get("wer") for t in takes),
            "wer_vs_asked": _mean(t.get("wer_vs_asked") for t in takes),
            "sim_o": _mean(t.get("sim_o") for t in takes),
            "utmos": _mean(t.get("utmos") for t in takes),
            "duration_error_s": _mean(t.get("duration_error_s") for t in takes),
            "plan_quality": quality["score"],
            "help_used": any(s.get("tool") == "search_help" for s in steps) if sc.question else None,
        },
        "plan_quality": quality,
        "cost": {"turn_usd": turn["total"], "turn_by": turn["by"], "setup_usd": setup_usd, "scoring_usd": round(scoring_usd, 5),
                 "tokens": {k: sum(r[k] for r in requests) for k in ("input", "cache_read", "cache_write", "output")},
                 "requests": len(requests)},
    }


def run(base: str, db: Path, log: Path, label: str, only: list[str] | None, cap: float, budget: float,
        out_dir: Path = RESULTS) -> Path:
    api = Api(base)
    # AVE_EVAL_STT=openai|elevenlabs picks the scorer that hears the takes (ElevenLabs by default).
    use = os.environ.get("AVE_EVAL_STT", "elevenlabs")
    keys = {"openai": os.environ.get("OPENAI_API_KEY")} if use == "openai" else {"elevenlabs": os.environ.get("ELEVENLABS_API_KEY")}
    keys = {k: v for k, v in keys.items() if v}
    if not keys:
        print("No speech to text key: WER is not scored.", flush=True)
    chosen = [s for s in SCENARIOS if not only or s.name in only]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stamp}-{label or 'run'}.json"
    runs, spent = [], 0.0
    for n, sc in enumerate(chosen, 1):
        estimate = ESTIMATE_USD.get(sc.name, 0.5)
        if spent + estimate > budget:
            print(f"[{n}/{len(chosen)}] {sc.name}: not run, ${spent:.2f} spent and its estimate ${estimate:.2f} "
                  f"would pass the ${budget:.2f} budget", flush=True)
            continue
        print(f"[{n}/{len(chosen)}] {sc.name} (estimate ${estimate:.2f}, spent ${spent:.2f})", flush=True)
        try:
            rec = run_one(api, sc, db, log, cap, keys)
        except Exception as exc:  # noqa: BLE001 - one broken scenario does not lose the others
            print(f"      failed: {exc}", flush=True)
            runs.append({"scenario": sc.name, "status": "error", "error": str(exc)[:500]})
            continue
        c = rec["cost"]
        spent += c["turn_usd"] + c["setup_usd"] + c["scoring_usd"]
        s = rec["scores"]
        print(f"      {rec['status']} · {rec['seconds']} s · turn ${c['turn_usd']:.4f} (setup ${c['setup_usd']:.4f}, "
              f"scoring ${c['scoring_usd']:.4f}) · WER {s['wer']} · SIM-o {s['sim_o']} · UTMOS {s['utmos']} · "
              f"dur {s['duration_error_s']} · plan {s['plan_quality']}", flush=True)
        runs.append(rec)
        out.write_text(json.dumps({"label": label, "stamp": stamp, "spent_usd": round(spent, 5), "runs": runs},
                                  ensure_ascii=False, indent=1))
    out.write_text(json.dumps({"label": label, "stamp": stamp, "spent_usd": round(spent, 5), "runs": runs},
                              ensure_ascii=False, indent=1))
    print(f"\n${spent:.4f} spent in all → {out}")
    return out
