"""G4: the notification bell and its settings (routes).

Everything here is the signed-in person's own (with sign-in off, `local`):
their notifications, unread count and per-kind settings. The bell polls
`GET /me/notifications/count`. Needs `golive.g4`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.notify import inbox

router = APIRouter(tags=["notifications"])


def _api():
    from app.api import main
    return main


def _user(request: Request) -> str:
    api = _api()
    user = api.signed_in_user(request)
    if request.method not in ("GET", "HEAD") and api.settings.auth_mode != "off" \
            and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    if not api.flags.enabled("golive.g4", user):
        raise HTTPException(status_code=404, detail="Not found")
    return user


@router.get("/me/notifications")
def list_notifications(request: Request, limit: int = 30) -> dict:
    """Newest first, with how many are unread."""
    user = _user(request)
    db = _api().database
    return {"items": inbox.list_for(db, user, limit), "unread": inbox.unread(db, user)}


@router.get("/me/notifications/count")
def unread_count(request: Request) -> dict:
    return {"unread": inbox.unread(_api().database, _user(request))}


class ReadRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = False


@router.post("/me/notifications/read")
def mark_read(req: ReadRequest, request: Request) -> dict:
    """Mark some read (`ids`), or all of them (`all: true`)."""
    user = _user(request)
    db = _api().database
    inbox.mark_read(db, user, None if req.all else (req.ids or []))
    return {"unread": inbox.unread(db, user)}


@router.get("/me/notifications/settings")
def get_settings(request: Request) -> dict:
    return {"kinds": inbox.settings(_api().database, _user(request))}


@router.put("/me/notifications/settings")
def put_settings(changes: dict[str, dict], request: Request) -> dict:
    """{kind: {in_app?, email?}} for any kinds; the whole list comes back."""
    user = _user(request)
    try:
        return {"kinds": inbox.set_settings(_api().database, user, changes)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
