"""The guided run on the sample ad (Tutorial map and Help, 2026-10-19).

A tutorial video is the bundled sample ad with a recorded transcript, and
its turns replay one real run (`fixture/script.json`: the steps Voltage
took, the gate it asked, the take it voiced and what it said). No vendor is
called and the ledger stays at $0.00; Add it and Export then go through the
real render, which is free. Everything else about the video is ordinary, so
leaving the tour keeps it.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.domain.models import Consent, Selection, Source
from app.domain.plan import Plan, PlanItem
from app.store import codec

FIXTURE = Path(__file__).resolve().parent / "fixture"
FILENAME = "sample-ad.mp4"
STEP_PAUSE = 0.7   # seconds between replayed steps, so the trace reads as it happens

ONE_EDIT = "The tutorial covers one edit. Upload your own clip to keep going."


def _api():
    from app.api import main
    return main


def _owner(request: Request) -> str:
    return _api().current_owner(request)


def _script() -> dict:
    return json.loads((FIXTURE / "script.json").read_text(encoding="utf-8"))


def is_tutorial(repo, video_id: str) -> bool:
    return bool(repo.settings(video_id).get("tutorial"))


def _now() -> str:
    return _api()._now()


def start(owner: str) -> dict:
    """The sample ad as a fresh tutorial video for this owner: media copied
    into the store, the recorded transcript and reading, consent recorded
    (it is our own clip), no charge."""
    api = _api()
    repo, artifacts = api.repo, api.artifacts
    video_id = repo.next_id()
    probe = codec.source(json.loads((FIXTURE / "source.json").read_text())) if (FIXTURE / "source.json").exists() else None
    duration = probe.duration if probe else 2.3
    media = artifacts.put_file(video_id, FIXTURE / FILENAME, kind="video", container="mp4", duration=duration)
    source = Source(project_id=video_id, filename=FILENAME, duration=duration, media=media)
    transcript = codec.transcript(json.loads((FIXTURE / "transcript.json").read_text(encoding="utf-8")))
    repo.create(source, transcript, Consent(granted_at=_now()), owner=owner)
    reading = json.loads((FIXTURE / "reading.json").read_text(encoding="utf-8"))
    repo.set_settings(video_id, **api._starting_settings(owner), tutorial=True, reading=reading)
    return api._project_dict(repo.get(video_id))


def _plan_for(repo, video_id: str, text: str) -> Plan:
    plan = repo.latest_plan(video_id)
    if plan is not None:
        return plan
    item = PlanItem(**{k: v for k, v in _script()["item"].items() if k in PlanItem.__dataclass_fields__})
    if isinstance(item.selection, dict):
        item = replace(item, selection=Selection(**item.selection))
    plan = Plan(plan_id=repo.next_plan_id(video_id), project_id=video_id, goal=text, summary="", items=(item,),
                mode="ask", status="proposed", created_at=_now())
    repo.save_plan(plan)
    return plan


def replay_turn(repo, video_id: str, text: str, owner: str) -> dict:
    """The recorded turn that comes next, as a job: the first turn reads the
    line and asks for a go; the second (any yes) voices the take and says
    what it did. Anything after the edit is one sentence and no job."""
    api = _api()
    jobs, runner = api.jobs, api.runner
    if any(j.kind == "turn" and j.project_id == video_id and not j.done for j in jobs.all()):
        raise HTTPException(status_code=409, detail="Voltage is still on the last thing you said.")
    script = _script()
    plan = _plan_for(repo, video_id, text)
    item = plan.items[0]
    if item.status in ("ready", "approved", "dismissed"):
        raise HTTPException(status_code=409, detail=ONE_EDIT)
    # Past the gate once asked, even after a "Not yet" cleared the question.
    asked = bool(plan.question) or any(str(e.get("text", "")).startswith("Asked:") for e in plan.log)
    which = 1 if asked else 0
    yes = str(plan.question["options"][0]).lower() if plan.question else "go ahead"
    if which == 1 and not (api.is_go(text) or text.strip().lower() == yes):
        # A no, or anything else at the gate: the plan waits where it was; nothing is said for Voltage.
        if text.strip().lower() == "not yet":
            repo.add_message(video_id, "user", text)
            repo.update_plan(video_id, plan.plan_id, status="proposed", question=None)
            job = jobs.create("turn", video_id)
            jobs.update(job.job_id, status="succeeded", progress=1.0, step="Done",
                        result={"type": "turn", "plan": api._plan_dict(repo.get_plan(video_id, plan.plan_id)), "reply": None, "question": None,
                                "spent_usd": 0.0, "calls": 0, "stopped": "done"})
            return api._job_dict(jobs.get(job.job_id))
        which = 1   # any other words at the gate are taken as the go: the tour's one path
    turn = script["turns"][which]
    repo.add_message(video_id, "user", text)
    repo.update_plan(video_id, plan.plan_id, status="running", question=None)
    job = jobs.create("turn", video_id)

    def work(report) -> dict:
        n = len(turn["steps"])
        for k, step in enumerate(turn["steps"], 1):
            time.sleep(STEP_PAUSE)
            repo.add_message(video_id, "assistant", step["text"], kind="step", cost=None,
                             data={"tool": step.get("tool") or "", "t": float(step.get("t") or 0.0)})
            repo.append_log(video_id, plan.plan_id, step["text"], "")
            report(0.1 + 0.8 * k / n, step["text"])
        question = turn.get("question")
        reply = turn.get("reply")
        if which == 1:
            _voice_the_take(repo, api.artifacts, video_id, plan.plan_id, item.item_id)
        if reply:
            repo.add_message(video_id, "assistant", reply)
        if question:
            repo.add_message(video_id, "assistant", question["text"])
            repo.append_log(video_id, plan.plan_id, f"Asked: {question['text']}")
        updated = repo.get_plan(video_id, plan.plan_id)
        repo.update_plan(video_id, plan.plan_id, status="clarifying" if question else "done", question=question,
                         summary=reply or updated.summary, estimate=api._estimate(video_id, updated.items))
        return {"type": "turn", "plan": api._plan_dict(repo.get_plan(video_id, plan.plan_id)), "reply": reply,
                "question": question, "spent_usd": 0.0, "calls": len(turn["steps"]), "stopped": "done"}

    def failed() -> None:
        repo.update_plan(video_id, plan.plan_id, status="proposed")

    submitted = runner.submit(job, api._guarded(work, failed))
    return api._job_dict(submitted)


def _voice_the_take(repo, artifacts, video_id: str, plan_id: str, item_id: str) -> None:
    """The recorded take, copied into this video's store under a new id, and the item made ready with it."""
    body = json.loads((FIXTURE / "candidate.json").read_text(encoding="utf-8"))
    audio = artifacts.put_file(video_id, FIXTURE / f"audio.{body['audio']['container']}", kind="audio",
                               container=body["audio"]["container"], duration=body["audio"]["duration"])
    frames = artifacts.put_file(video_id, FIXTURE / f"frames.{body['frames']['container']}", kind="video",
                                container=body["frames"]["container"], duration=body["frames"]["duration"])
    candidate_id = repo.next_candidate_id(video_id)
    cand = codec.candidate({**body, "candidate_id": candidate_id, "audio": codec.dump(audio), "frames": codec.dump(frames)})
    repo.save_candidate(video_id, cand)
    repo.update_item(video_id, plan_id, item_id, status="ready", candidate_id=candidate_id, progress=None)


router = APIRouter(tags=["tutorial"])


@router.post("/tutorial", status_code=201)
def start_tutorial(owner: str = Depends(_owner)) -> dict:
    """The guided run's video: the sample ad, read already, free to play with."""
    if not FIXTURE.exists():
        raise HTTPException(status_code=503, detail="The tutorial's recording is not installed.")
    return start(owner)
