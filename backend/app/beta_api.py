"""Beta kit (routes).

The signed-in person (any role; asked once, after their first export):
    GET  /me/beta-survey            {due, questions}: due for someone in the cohort who has
                                    exported and was never shown them
    POST /me/beta-survey/shown      {video_id?}: they are on screen now, so never again
    POST /me/beta-survey            {useful, almost_stopped?, would_pay, video_id?}: 201, once (409 after)

Admins only (AVE_ADMIN_OWNERS; everyone else gets 404):
    POST /admin/beta/join     {who, email?}: `who` is an owner id or an address; into the
                              cohort (app.beta.join: its flags on, $10 of credits once),
                              audited; with email (the default) the beta invite goes to
                              their address, worded for someone with an account
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import admin, analytics, beta

router = APIRouter(tags=["beta"])


def _api():
    from app.api import main
    return main


def _admin_writer(request: Request) -> str:
    from app.admin_api import _admin
    return _admin(request)


def _who(text: str) -> str:
    """An owner id Voltage knows, or the one person with exactly this address."""
    from app.admin_api import _known
    text = text.strip()
    if "@" in text and not text.startswith(("acct:", "google:", "email:")):
        owners = [r["owner"] for r in admin.find(_api().database, text) if text.lower() in r["emails"]]
        if len(owners) != 1:
            raise HTTPException(status_code=404, detail="Nobody has signed in with that address." if not owners
                                else "More than one person has that address. Use their owner id.")
        return owners[0]
    return _known(text)


class Join(BaseModel):
    who: str = Field(min_length=2, max_length=320)
    email: bool = True


@router.post("/admin/beta/join")
def join_beta(req: Join, who: str = Depends(_admin_writer)) -> dict:
    api = _api()
    owner = _who(req.who)
    made = beta.join(api.database, api.flags, owner)
    admin.audit(api.database, who, "beta_join", owner, "", {"credits": made["credits"], "again": not made["joined"]})
    sent = False
    if req.email and made["joined"]:
        to = admin.proven_address(api.database, owner)
        sent = bool(to) and beta.invite_email(api, to, existing=True)
    return {"owner": owner, **made, "emailed": sent}


def _people(request: Request) -> tuple[str, str, str | None]:
    """The signed-in person, the owner of the workspace they act in (the flags and the
    exports are that owner's), and the workspace."""
    api = _api()
    owner = api.current_owner(request)
    person = api.signed_in_user(request)
    me = api.acting.get()
    wid = me.workspace_id if me and me.workspace_id else None
    return person, owner, wid


def _video(video_id: str | None, owner: str) -> str | None:
    vid = " ".join((video_id or "").split())[:64]
    record = _api().repo.get(vid) if vid else None
    return vid if record is not None and record.owner == owner else None


@router.get("/me/beta-survey")
def get_survey(request: Request) -> dict:
    api = _api()
    person, owner, _ = _people(request)
    return {"due": beta.survey_due(api.database, api.flags, person, owner), "questions": list(beta.QUESTIONS)}


class Shown(BaseModel):
    video_id: str | None = Field(default=None, max_length=64)


@router.post("/me/beta-survey/shown")
def survey_shown(request: Request, req: Shown | None = None) -> dict:
    api = _api()
    person, owner, wid = _people(request)
    if beta.survey_due(api.database, api.flags, person, owner) and \
            beta.survey_shown(api.database, person, wid, _video(req.video_id if req else None, owner)):
        analytics.track("beta.survey_shown", person)
    return {"due": False}


class Answers(BaseModel):
    useful: str = Field(max_length=20)
    almost_stopped: str | None = Field(default=None, max_length=beta.MAX_WORDS)
    would_pay: str = Field(max_length=20)
    video_id: str | None = Field(default=None, max_length=64)


@router.post("/me/beta-survey", status_code=201)
def answer_survey(req: Answers, request: Request) -> dict:
    api = _api()
    person, owner, wid = _people(request)
    if not beta.in_cohort(api.flags, owner):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        beta.survey_answer(api.database, person, wid, req.useful, req.almost_stopped, req.would_pay, _video(req.video_id, owner))
    except beta.SurveyDone as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    analytics.track("beta.survey_answered", person, {"useful": req.useful, "would_pay": req.would_pay})
    return {"said": beta.THANKS}
