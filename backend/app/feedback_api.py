"""G8: thumbs on takes and turns, and the browser's error reports (routes).

    GET  /videos/{id}/feedback     your votes on this video's takes and replies
    PUT  /videos/{id}/feedback     {target: take|turn, target_id, vote: up|down|null, reason?}
    POST /errors                   {message, stack?, where?, kind?}: window.onerror,
                                   unhandledrejection or the React error boundary;
                                   rate limited, stored through the error reporter

Feedback needs `golive.g8` for the signed-in person; error reports are taken
from anyone signed in (with the flag) and limited to 20 a minute each.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.ratelimit import RateLimit
from app.store import feedback

router = APIRouter(tags=["feedback"])
error_reports = RateLimit(20, 60.0)


def _api():
    from app.api import main
    return main


def _flag(owner: str) -> None:
    if not _api().flags.enabled("golive.g8", owner):
        raise HTTPException(status_code=404, detail="Not found")


def _owner(request: Request) -> str:
    return _api().current_owner(request)


class FeedbackRequest(BaseModel):
    target: str
    target_id: str
    vote: str | None
    reason: str = ""


@router.get("/videos/{video_id}/feedback")
def get_feedback(video_id: str, request: Request, owner: str = Depends(_owner)) -> dict:
    _flag(owner)
    _api()._owned(video_id, owner)
    return feedback.for_video(_api().database, _api().signed_in_user(request), video_id)


@router.put("/videos/{video_id}/feedback")
def put_feedback(video_id: str, req: FeedbackRequest, request: Request, owner: str = Depends(_owner)) -> dict:
    _flag(owner)
    _api()._owned(video_id, owner)
    who = _api().signed_in_user(request)
    try:
        return feedback.give(_api().database, who, video_id, req.target, req.target_id, req.vote, req.reason)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class ErrorReport(BaseModel):
    message: str = Field(max_length=4000)
    stack: str = Field(default="", max_length=8000)
    where: str = Field(default="", max_length=500)
    kind: str = Field(default="error", max_length=40)


@router.post("/errors", status_code=204)
def report_error(req: ErrorReport, request: Request) -> Response:
    api = _api()
    user = api.signed_in_user(request)
    if request.method != "GET" and api.settings.auth_mode != "off" \
            and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    _flag(user)
    if not error_reports.allow(user):
        raise HTTPException(status_code=429, detail="Too many reports. Try again in a minute.")
    api.error_reporter.capture_message(req.message, "error", {"source": "client", "owner": user, "where": req.where,
                                                              "stack": req.stack, "kind": req.kind})
    return Response(status_code=204)
