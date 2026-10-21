"""G7: the browser's events and the internal admin page (routes).

    POST /analytics/events   {name, props}: a client-side name from the allow-list
    GET  /me/admin           {admin}: whether the admin page is yours
    GET  /admin/analytics    the funnel, take acceptance, cost per exported
                             minute, SIM-o and UTMOS per vendor (measured only),
                             counts per event

Everything needs `golive.g7` for the signed-in person. The admin page is for
the owners in AVE_ADMIN_OWNERS (default `local`); anyone else gets 404, so
the page's existence is not advertised.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import analytics
from app.ratelimit import RateLimit

router = APIRouter(tags=["analytics"])
# A browser sends a handful a minute; 120 is generous and stops a loop.
client_events = RateLimit(120, 60.0)


def _api():
    from app.api import main
    return main


def _user(request: Request, flag: str = "golive.g7") -> str:
    api = _api()
    user = api.signed_in_user(request)
    if request.method not in ("GET", "HEAD") and api.settings.auth_mode != "off" \
            and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    if not api.flags.enabled(flag, user):
        raise HTTPException(status_code=404, detail="Not found")
    return user


def is_admin(user: str) -> bool:
    return user in _api().settings.admin_owners


class ClientEvent(BaseModel):
    name: str = Field(max_length=80)
    props: dict = Field(default_factory=dict)


@router.post("/analytics/events", status_code=204)
def client_event(req: ClientEvent, request: Request) -> Response:
    """One event from the browser. Only CLIENT_NAMES; 429 past the rate limit."""
    user = _user(request)
    if req.name not in analytics.CLIENT_NAMES:
        raise HTTPException(status_code=422, detail="That event name is not on the list.")
    if not client_events.allow(user):
        raise HTTPException(status_code=429, detail="Too many events. Try again in a minute.")
    analytics.track(req.name, user, req.props, source="client", db=_api().database)
    return Response(status_code=204)


@router.get("/me/admin")
def me_admin(request: Request) -> dict:
    api = _api()
    user = api.signed_in_user(request)
    return {"admin": api.flags.enabled("golive.g7", user) and is_admin(user)}


@router.get("/admin/analytics")
def admin_analytics(request: Request) -> dict:
    """The internal numbers (admins only)."""
    user = _user(request)
    if not is_admin(user):
        raise HTTPException(status_code=404, detail="Not found")
    db = _api().database
    out = {"funnel": analytics.funnel(db), "take_acceptance": analytics.take_acceptance(db),
           "cost_per_exported_minute": analytics.cost_per_exported_minute(db),
           "vendor_quality": analytics.vendor_quality(db), "counts": analytics.counts(db)}
    try:                                    # G8: thumbs, when that store is here
        from app.store import feedback
        out["feedback"] = feedback.summary(db)
    except ImportError:
        pass
    try:                                    # G6: abuse reports, newest first
        from app.safety_api import recent_reports
        out["abuse_reports"] = recent_reports()
    except ImportError:
        pass
    return out
