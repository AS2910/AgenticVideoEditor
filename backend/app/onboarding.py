"""What a person has met so far (Tutorial map and Help, 2026-10-19): the tour
step reached, finished or skipped; the tips seen; the checklist items done;
whether the checklist is hidden. One record per owner, in `meta` under
`onboarding:{owner}`, so it follows them across devices.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

TIPS = (
    "first-upload", "first-silent", "first-question", "first-just-do-it", "first-voice-design",
    "first-project-voice", "first-background", "first-undo-after-export", "first-ceiling", "first-failed-take",
)
CHECKLIST = ("goal", "add", "export", "save-voice", "autonomy")


def _owner(request: Request) -> str:
    # The API module owns sign-in; importing it here (not at load) avoids the circle.
    from app.api.main import current_owner
    return current_owner(request)


def _repo():
    from app.api.main import repo
    return repo


def default() -> dict:
    return {"tour": {"step": 0, "finished": False, "skipped": False}, "tips": [], "checklist": [], "checklist_hidden": False}


def read(owner: str) -> dict:
    saved = json.loads(_repo().get_meta(f"onboarding:{owner}") or "{}")
    base = default()
    tour = {**base["tour"], **(saved.get("tour") or {})}
    return {
        "tour": {"step": int(tour.get("step", 0)), "finished": bool(tour.get("finished")), "skipped": bool(tour.get("skipped"))},
        "tips": [t for t in saved.get("tips", []) if t in TIPS],
        "checklist": [c for c in saved.get("checklist", []) if c in CHECKLIST],
        "checklist_hidden": bool(saved.get("checklist_hidden", False)),
    }


class Tour(BaseModel):
    step: int | None = None
    finished: bool | None = None
    skipped: bool | None = None


class OnboardingUpdate(BaseModel):
    tour: Tour | None = None
    tips: list[str] | None = None
    checklist: list[str] | None = None
    checklist_hidden: bool | None = None


def mark(owner: str, *, tip: str | None = None, checklist: str | None = None) -> dict:
    """A tip shown or a checklist item done by a real action (the API's own events call this)."""
    state = read(owner)
    if tip in TIPS and tip not in state["tips"]:
        state["tips"].append(tip)
    if checklist in CHECKLIST and checklist not in state["checklist"]:
        state["checklist"].append(checklist)
    _repo().set_meta(f"onboarding:{owner}", json.dumps(state))
    return state


router = APIRouter(tags=["onboarding"])


@router.get("/me/onboarding")
def get_onboarding(owner: str = Depends(_owner)) -> dict:
    return read(owner)


@router.put("/me/onboarding")
def update_onboarding(req: OnboardingUpdate, owner: str = Depends(_owner)) -> dict:
    """Any subset; lists are unions (a tip once seen stays seen), the tour and the flag replace."""
    state = read(owner)
    if req.tour is not None:
        for k in ("step", "finished", "skipped"):
            v = getattr(req.tour, k)
            if v is not None:
                state["tour"][k] = v
    if req.tips is not None:
        state["tips"] = sorted({*state["tips"], *(t for t in req.tips if t in TIPS)}, key=TIPS.index)
    if req.checklist is not None:
        state["checklist"] = sorted({*state["checklist"], *(c for c in req.checklist if c in CHECKLIST)}, key=CHECKLIST.index)
    if req.checklist_hidden is not None:
        state["checklist_hidden"] = req.checklist_hidden
    _repo().set_meta(f"onboarding:{owner}", json.dumps(state))
    return state
