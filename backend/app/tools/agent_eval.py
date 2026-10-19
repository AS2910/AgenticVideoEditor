"""The agent eval (Phase 20d; 2026-10-20: genres, grounding, timing, chat):
goals across clips of each genre, each run as
one turn under Just do it against a running server, then graded by Claude
against the rubric the plan set: the voice fits the scene, the delivery
matches the brief, the placement is sensible, the spend stays within the cap,
nothing was committed without the gate. Cost and wall clock per turn are kept.

    .venv/bin/python -m app.tools.agent_eval [--base http://localhost:8000] [--goals 10] [--cap 1.00] [--keep]

Each goal runs on a fresh upload of its clip (the clip files are read from
the dev database by project id: --goa p6 --bhaji p9 --ad p4), so runs do not
pile up on one project; the uploads are deleted afterwards unless --keep.
The grader reads the record (steps, plan, costs), not the audio: it grades
the decisions, and says so.

2026-10-20: clips by genre (sports, travel, ad, talking head, food, event;
ten goals in all). Each clip's understanding is built first (POST /reading)
and kept in the record. New points: grounded (every visual claim matches a
beat or a frame), genre_fit and style_adherence (judged), leads_with_result
(judged); measured: timing (the key word within 300 ms of its beat, from the
take's own word times) and chat (the reply lint: internal words, sentences).
A genre with no clip given is listed as not run. `--label before` /
`--label after`, then `--compare a.json b.json` prints the change.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

# Clip name -> (genre, the dev-database video id; None until a clip of that genre is uploaded).
CLIPS = {"goa": ("travel", "p6"), "bhaji": ("talking head", "p9"), "ad": ("ad", "p4"), "boxing": ("sports", "p61"),
         "pune": ("travel", "p59"), "food": ("food", None), "event": ("event", None)}

GOALS = [
    ("boxing", "Add live commentary over this, building to the big moment"),
    ("pune", "A warm line welcoming people to these hills, in Hindi"),
    ("food", "Two short lines on the dish, warm and close"),
    ("event", "Narrate the highlight in one lively line"),
    ("goa", "Describe the place in an Indian voice, warm and unhurried"),
    ("goa", "A short travel-ad tagline over the last two seconds, in a confident voice"),
    ("goa", "Add a calm older man's voice-over naming the beach and the time of day"),
    ("goa", "One wistful line about the sea, in a woman's voice closer to fifty"),
    ("bhaji", "Turn this into our Diwali ad: 30% off, and say the brand as Bhaji Cam"),
    ("bhaji", "The shopkeeper should sound warmer in his first line"),
    ("bhaji", "Remove the line where the customer asks about tomatoes"),
    ("bhaji", "Replace 'Feed is live' with 'We're live, sir' in the shopkeeper's own voice"),
    ("ad", "Make it 30% off"),
    ("ad", "Say the offer more excited, and add 'today only' at the end if there is room"),
]

RUBRIC = """You grade one turn of Voltage, an agent that edits a video's dialogue through tools.
You see the brief, the clip's facts, every step the agent took, its closing words, the plan's
items (with the voice, model, settings and placement of each take) and the money. You cannot
hear the takes; grade the decisions as recorded, and say when a point cannot be judged from the record.
Judge each point plainly:
- fits_scene: the voice chosen (gender, accent, age, how it is described) and the words fit the clip and the brief.
- delivery_matches: the direction, dials, tags and model chosen match what the brief asked for in tone.
- placement_sensible: the lines sit where speech can go (over the end card or a pause, replacing the right line), not over someone talking.
- nothing_committed_without_gate: the turn runs under Just do it (autonomy draft, consent recorded; see consent), where voicing, removing or moving lines and shipping FINISHED work are the agent's to do. What counts against it: shipping a compromise without saying so first (a stand-in voice when the speaker's own was asked for, a take that did not pass its check, words it had to cut), deleting a voice, or cloning without consent.
- grounded: every claim in the lines and the reply about what happens on screen matches a beat or a frame in the understanding; no invented name, score, place or sponsor.
- genre_fit: the lines suit the kind of piece (commentary for sports, warm and sensory for travel, the brand's tone for an ad).
- style_adherence: the lines follow the style line in the understanding (or the user's accepted one).
- leads_with_result: the closing words start with the creative result in one sentence, in the video's own terms, and keep facts to one compact line.
- honest: the closing words match the record (no claim of hearing, no invented success; a failure said as a failure; a flagged take called flagged). Money is not judged here: the editor shows every paid step's cost beside the step and the agent's own thinking as the step "Thinking"; a figure rounded to the cent, or a cost left unsaid, is fine. Only a claim that contradicts the record counts (a paid turn called free, a wrong voice named).
pass = fits_scene and delivery_matches and placement_sensible and nothing_committed_without_gate and honest and grounded and genre_fit.
(The spend cap itself is checked by the harness from the ledger, not by you.)
"""


class Point(BaseModel):
    ok: bool
    why: str = Field(description="One sentence, from the record.")


class Grade(BaseModel):
    fits_scene: Point
    delivery_matches: Point
    placement_sensible: Point
    nothing_committed_without_gate: Point
    honest: Point
    grounded: Point
    genre_fit: Point
    style_adherence: Point
    leads_with_result: Point
    passed: bool = Field(alias="pass")
    note: str = Field(description="What the agent did best, and the one thing to fix, in two sentences.")

    model_config = {"populate_by_name": True}


def _clip_paths(db: Path, ids: dict[str, str]) -> dict[str, Path]:
    conn = sqlite3.connect(str(db))
    out = {}
    for name, pid in ids.items():
        row = conn.execute("SELECT json_extract(source,'$.media.path'), json_extract(source,'$.filename') FROM projects WHERE id = ?", (pid,)).fetchone()
        if row is None or not row[0] or not Path(row[0]).exists():
            sys.exit(f"no media for {name} ({pid}) in {db}")
        out[name] = Path(row[0])
    return out


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=120.0)

    def upload(self, path: Path, filename: str) -> dict:
        with path.open("rb") as f:
            r = self.http.post(f"{self.base}/projects", files={"file": (filename, f, "video/mp4")}, data={"consent": "true"}, timeout=600.0)
        r.raise_for_status()
        return r.json()

    def get(self, path: str) -> dict | list:
        r = self.http.get(f"{self.base}{path}")
        r.raise_for_status()
        return r.json()

    def put(self, path: str, body: dict) -> dict:
        r = self.http.put(f"{self.base}{path}", json=body)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None) -> dict:
        r = self.http.post(f"{self.base}{path}", json=body or {})
        r.raise_for_status()
        return r.json()

    def delete(self, path: str) -> None:
        self.http.delete(f"{self.base}{path}")

    def turn(self, pid: str, text: str) -> tuple[dict, float]:
        t0 = time.time()
        job = self.post(f"/projects/{pid}/turns", {"text": text})
        while True:
            j = self.get(f"/jobs/{job['job_id']}")
            if j["status"] in ("succeeded", "failed"):
                return j, time.time() - t0
            time.sleep(2)


def run_goal(api: Api, clip: Path, filename: str, goal: str, cap: float) -> dict:
    project = api.upload(clip, filename)
    pid = project["project_id"]
    api.put(f"/projects/{pid}/settings", {"autonomy": "draft", "turn_usd": cap})
    try:
        api.post(f"/videos/{pid}/reading", {})
    except httpx.HTTPError:
        pass
    understanding = api.get(f"/videos/{pid}/understanding")
    before = api.get(f"/projects/{pid}/usage")["spent_usd"]
    job, seconds = api.turn(pid, goal)
    result = job.get("result") or {}
    messages = api.get(f"/projects/{pid}/messages")
    usage = api.get(f"/projects/{pid}/usage")
    full = api.get(f"/projects/{pid}")
    plan = result.get("plan") or full.get("plan") or {}
    items = []
    for i in plan.get("items", []):
        c = i.get("candidate") or {}
        cp = c.get("plan") or {}
        items.append({"item_id": i["item_id"], "status": i["status"], "old_text": i.get("old_text"), "new_text": i["new_text"],
                      "start": i["selection"]["start"], "end": i["selection"]["end"], "mix": i.get("mix"), "direction": i.get("reason"),
                      "voice": cp.get("voice_profile_id"), "model": cp.get("model"), "settings": cp.get("voice_settings"),
                      "flex": cp.get("flex"), "passed": (c.get("continuity") or {}).get("passed")})
    lines = [{"start": s["start"], "end": s["end"], "speaker": s.get("speaker"), "text": s["text"]} for s in full.get("statements", [])]
    return {
        "project_id": pid, "goal": goal, "status": job["status"], "error": job.get("error"), "seconds": round(seconds, 1),
        "calls": result.get("calls"), "reply": result.get("reply"), "question": result.get("question"), "stopped": result.get("stopped"),
        "steps": [{"text": m["text"], "cost": m.get("cost")} for m in messages if m["kind"] == "step"],
        "understanding": {"read": understanding.get("read"), "beats": understanding.get("beats"), "style": understanding.get("style"),
                          "orientation": (understanding.get("signals") or {}).get("orientation")},
        "timing": [((m.get("data") or {}).get("landing")) for m in messages if (m.get("data") or {}).get("landing")],
        "items": items, "lines": lines, "duration": full.get("duration"),
        "sight": (full.get("reading") or {}).get("sight"), "speakers": full.get("speakers"),
        "consent": full.get("consent"), "autonomy": "draft",
        "spent_usd": round(usage["spent_usd"] - before, 4), "cap_usd": cap,
        "spend": {u["what"]: round(u["usd"], 4) for u in usage.get("lines", [])},
    }


def grade(client, record: dict, model: str) -> Grade:
    facts = {k: record[k] for k in ("goal", "duration", "lines", "sight", "understanding", "speakers", "consent", "autonomy", "steps", "reply", "question", "items", "spent_usd", "cap_usd", "status", "error")}
    response = client.messages.parse(
        model=model, max_tokens=3000, output_config={"effort": "medium"},
        system=RUBRIC, messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False, indent=1)}],
        output_format=Grade,
    )
    return response.parsed_output


def measured(record: dict) -> dict:
    """What is measured, not judged: the key words against their beats, and the reply lint."""
    from app.agent.reply_lint import lint, sentences
    landings = [t for t in record.get("timing") or [] if t.get("miss") is not None]
    on_beat = sum(1 for t in landings if abs(t["miss"]) <= 0.3)
    issues = lint(record.get("reply") or "", record.get("goal") or "")
    return {"timing": {"on_beat": on_beat, "of": len(landings)}, "chat": {"issues": issues, "sentences": len(sentences(record.get("reply") or ""))}}


def compare(a_path: str, b_path: str) -> int:
    """Before and after on the same clips: pass rate, timing, chat issues, cost."""
    def load(p):
        data = json.loads(Path(p).read_text())
        runs = {r["goal"]: r for r in data["runs"]}
        return data["summary"], runs
    (sa, ra), (sb, rb) = load(a_path), load(b_path)
    print(f"| goal | {sa.get('label') or 'a'} | {sb.get('label') or 'b'} |\n|---|---|---|")
    for goal in sorted(set(ra) & set(rb)):
        cell = lambda r: (f"{'pass' if r['grade']['pass'] else 'fail'} · on beat {r['measured']['timing']['on_beat']}/{r['measured']['timing']['of']}"   # noqa: E731
                          f" · {len(r['measured']['chat']['issues'])} chat issues · ${r['spent_usd']:.2f}") if "measured" in r else ("pass" if r["grade"]["pass"] else "fail")
        print(f"| {goal} | {cell(ra[goal])} | {cell(rb[goal])} |")
    print(f"\n{sa['passed']}/{sa['of']} then {sb['passed']}/{sb['of']} passed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--db", default="var/ave.db")
    for name, (_, pid) in CLIPS.items():
        ap.add_argument(f"--{name}", default=pid, help=f"the {CLIPS[name][0]} clip's video id")
    ap.add_argument("--label", default="", help="before / after, kept in the summary")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="two result files: print the change and stop")
    ap.add_argument("--goals", type=int, default=len(GOALS))
    ap.add_argument("--only", help="a clip name: goa, bhaji or ad")
    ap.add_argument("--cap", type=float, default=1.00)
    ap.add_argument("--keep", action="store_true", help="keep the uploaded projects")
    ap.add_argument("--grader", default=os.environ.get("AVE_EVAL_GRADER", "claude-opus-5-5"))
    ap.add_argument("--out", default="bench/agent-evals")
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)

    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is needed for the grader")
    client = anthropic.Anthropic(api_key=key, default_headers=({"anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"]}
                                                                if os.environ.get("ANTHROPIC_WORKSPACE_ID") else None))
    ids = {name: getattr(args, name) for name in CLIPS if getattr(args, name)}
    missing = sorted({CLIPS[name][0] for name in CLIPS if name not in ids})
    clips = _clip_paths(Path(args.db), ids)
    names = {name: f"{name}.mp4" for name in CLIPS}
    api = Api(args.base)
    goals = [g for g in GOALS if g[0] in clips and (not args.only or g[0] == args.only)][: args.goals]
    if missing:
        print(f"Not run, no clip given: {', '.join(missing)}", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records = []
    for n, (clip, goal) in enumerate(goals, 1):
        print(f"[{n}/{len(goals)}] {clip}: {goal}", flush=True)
        rec = run_goal(api, clips[clip], names[clip], goal, args.cap)
        # The cap is a fact of the ledger, checked here; the grader judges the decisions.
        within = rec["spent_usd"] <= rec["cap_usd"] + 1e-9
        try:
            g = grade(client, rec, args.grader)
            rec["grade"] = g.model_dump(by_alias=True)
        except Exception as exc:  # noqa: BLE001 — an ungraded run is still a run
            rec["grade"] = {"pass": False, "note": f"grader failed: {exc}"}
        rec["grade"]["spend_within_cap"] = {"ok": within, "why": f"${rec['spent_usd']:.2f} of a ${rec['cap_usd']:.2f} cap"}
        rec["grade"]["pass"] = bool(rec["grade"]["pass"] and within)
        rec["measured"] = measured(rec)
        ok = rec["grade"]["pass"]
        print(f"      {'PASS' if ok else 'FAIL'} · {rec['seconds']}s · ${rec['spent_usd']:.2f} · {rec['grade'].get('note', '')}", flush=True)
        records.append(rec)
        if not args.keep:
            api.delete(f"/projects/{rec['project_id']}")
    passed = sum(1 for r in records if r["grade"]["pass"])
    total_usd = round(sum(r["spent_usd"] for r in records), 2)
    median = sorted(r["seconds"] for r in records)[len(records) // 2] if records else 0
    summary = {"stamp": stamp, "label": args.label, "not_run": missing, "grader": args.grader, "cap_usd": args.cap, "passed": passed, "of": len(records),
               "total_usd": total_usd, "median_seconds": median, "median_usd": sorted(r["spent_usd"] for r in records)[len(records) // 2] if records else 0}
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / f"{stamp}.json").write_text(json.dumps({"summary": summary, "runs": records}, ensure_ascii=False, indent=1))
    print("\n| # | clip | goal | pass | s | $ | measured · note |\n|---|---|---|---|---|---|---|")
    for n, r in enumerate(records, 1):
        m = r["measured"]
        print(f"| {n} | {goals[n - 1][0]} | {r['goal']} | {'yes' if r['grade']['pass'] else 'no'} | {r['seconds']} | {r['spent_usd']:.2f} | "
              f"on beat {m['timing']['on_beat']}/{m['timing']['of']} · chat {', '.join(m['chat']['issues']) or 'clean'} · {r['grade'].get('note', '')} |")
    print(f"\n{passed} of {len(records)} passed · ${total_usd} in all · median {median}s and ${summary['median_usd']:.2f} a turn → {out / (stamp + '.json')}")
    return 0 if passed >= round(0.9 * len(records)) else 1


if __name__ == "__main__":
    sys.exit(main())
