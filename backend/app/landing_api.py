"""Launch item 8: what the public landing page reads, and the waitlist.

Public (no session):
    GET  /pricing                      plans, top-ups and the trial, from app/billing/prices.py
    POST /waitlist                     {email, name?, use_case?}: Request access. One answer
                                       whatever the address (no enumeration); rate limited
                                       per caller (ratelimit bucket `waitlist`)
Admins only (AVE_ADMIN_OWNERS):
    GET  /admin/waitlist               every request, newest first, waiting or invited
    POST /admin/waitlist/{id}/invite   emails the invite and marks the address invited:
                                       with `launch.invite_only` on it may then sign up
                                       (`accounts_api.may_join`). With {beta: true} (beta kit)
                                       the email is the beta invite, and the address joins the
                                       beta cohort at its first sign-in (`app.beta`)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import billing
from app.billing import prices
from app.billing.providers import provider_for
from app.store import accounts as accounts_store, waitlist

router = APIRouter(tags=["landing"])

JOINED = "Thanks. You are on the list, and we will email you when there is a place."


def _api():
    from app.api import main
    return main


def _price(usd: float) -> dict:
    return {"usd": billing.price(usd, None)[0], "inr": billing.price(usd, "IN")[0]}


@router.get("/pricing")
def pricing() -> dict:
    """The numbers the landing page shows, read from the billing config (never typed into the page)."""
    api = _api()
    provider = provider_for(None, api.settings)
    return {
        "trial_credits": billing.TRIAL_CREDITS,
        "credit_usd": 1.0,
        "plans": [{"plan_id": p.plan_id, "name": p.name, "credits": p.credits, "blurb": p.blurb,
                   "usd": p.usd, "inr": p.inr} for p in prices.PLANS.values()],
        "topups": [{"credits": t, **_price(round(t * prices.TOPUP_MARKUP, 2))} for t in prices.TOPUPS],
        "topup_months": prices.TOPUP_MONTHS,
        "test_mode": bool(provider.test_mode),
        # Phase B (language versions) is off in the public profile until an admin turns it on.
        "languages": api.flags.enabled("projects.batch"),
        "invite_only": api.settings.auth_mode != "off" and api.flags.enabled("launch.invite_only"),
    }


class Join(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=200)
    use_case: str | None = Field(default=None, max_length=1000)


@router.post("/waitlist", status_code=201)
def join(req: Join, request: Request) -> dict:
    api = _api()
    if request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    try:
        address = accounts_store.clean_email(req.email)
    except accounts_store.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    waitlist.join(api.database, address, req.name, req.use_case)
    # Same words for a new address, one already listed and one with an account.
    return {"ok": True, "message": JOINED}


def _admin(request: Request) -> str:
    api = _api()
    api.current_owner(request)            # signed in, and the CSRF header on a write
    return api._admin_or_404(request)


@router.get("/admin/waitlist")
def admin_waitlist(request: Request) -> dict:
    _admin(request)
    api = _api()
    from app import beta
    asked = beta.invited_addresses(api.database)
    return {"rows": [{**r, "beta": r["email"] in asked} for r in waitlist.rows(api.database)],
            "invite_only": api.flags.enabled("launch.invite_only")}


class Invite(BaseModel):
    beta: bool = False


@router.post("/admin/waitlist/{row_id}/invite")
def admin_invite(row_id: int, request: Request, req: Invite | None = None) -> dict:
    who = _admin(request)
    api = _api()
    row = waitlist.get(api.database, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    row = waitlist.invite(api.database, row_id, who)
    if req is not None and req.beta:
        from app import admin as admin_mod, beta
        beta.mark_invited(api.database, row["email"])
        beta.invite_email(api, row["email"], row.get("name"))
        admin_mod.audit(api.database, who, "beta_invite", row["email"], "", {"waitlist_id": row_id})
        return {"row": {**row, "beta": True}}
    try:
        from app.notify import templates
        # Item 9's access invite (HTML and text); the outbox kind stays waitlist_invite.
        api.email_sender.send(templates.email("access_invite", row["email"], public_url=api.settings.public_url,
                                              link=f"{api.settings.public_url}/#login", name=row.get("name"),
                                              sent_as="waitlist_invite"))
    except Exception:  # noqa: BLE001 - the row says invited; the log says the email failed
        api.log.exception("waitlist invite email")
    api.log.warning("waitlist %s invited by %s", row_id, who)
    from app import admin as admin_mod                     # item 10: every admin action is in the audit trail
    admin_mod.audit(api.database, who, "waitlist_invite", row["email"], "", {"waitlist_id": row_id})
    return {"row": row}
