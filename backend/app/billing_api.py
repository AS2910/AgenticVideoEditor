"""G3: billing (routes). Owner only (G2's role table keeps Editors and
Reviewers off /billing). Needs `golive.g3`; with it off the Billing page
keeps its plain "no billing in this build" view.

    GET  /billing                  plan, credits (granted, used, left, about N minutes), plans,
                                   top-ups, provider (test mode), billing details, invoices
    PUT  /billing/details          {country, legal_name?, gstin?, state_code?}
    POST /billing/plan             {plan}: through the fake provider; an invoice
    POST /billing/topup            {credits}: through the fake provider; an invoice
    GET  /billing/invoices/{id}    the invoice as a printable HTML page
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import analytics, billing
from app.billing import gst
from app.billing.providers import provider_for

router = APIRouter(tags=["billing"])


def _api():
    from app.api import main
    return main


def _owner(request: Request) -> str:
    owner = _api().current_owner(request)
    if not _api().flags.enabled("golive.g3", owner):
        raise HTTPException(status_code=404, detail="Not found")
    return owner


def spent_since(owner: str):
    return lambda at: _api().ledger.spent_usd_by_owner(owner, at)


def seller() -> dict:
    s = _api().settings
    return {"name": s.seller_name, "gstin": s.seller_gstin, "state": s.seller_state}


def view(owner: str) -> dict:
    db = _api().database
    acct = billing.account(db, owner)
    got = billing.credits(db, owner, spent_since(owner))
    per_minute = analytics.cost_per_exported_minute(db)["per_minute"]
    # "About N minutes" only when a cost per exported minute has been measured; no guess otherwise.
    minutes = int(got["left"] / per_minute) if per_minute and got["left"] > 0 else (0 if per_minute else None)
    provider = provider_for(acct["country"])
    return {
        "account": acct, "credits": {**got, "minutes": minutes},
        "plan": next((p for p in billing.plans_for(acct["country"]) if p["plan_id"] == acct["plan"]), None),
        "plans": billing.plans_for(acct["country"]), "topups": billing.topups_for(acct["country"]),
        "provider": {"name": provider.name, "label": provider.label, "test_mode": provider.test_mode},
        "trial_credits": billing.TRIAL_CREDITS, "invoices": billing.invoices(db, owner),
        "states": [{"code": k, "name": v} for k, v in sorted(gst.STATES.items(), key=lambda kv: kv[1])],
    }


@router.get("/billing")
def get_billing(owner: str = Depends(_owner)) -> dict:
    return view(owner)


class DetailsRequest(BaseModel):
    country: str | None = None
    legal_name: str = ""
    gstin: str = ""
    state_code: str | None = None


@router.put("/billing/details")
def put_details(req: DetailsRequest, owner: str = Depends(_owner)) -> dict:
    try:
        billing.set_details(_api().database, owner, country=req.country, legal_name=req.legal_name, gstin=req.gstin,
                            state_code=req.state_code)
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return view(owner)


class PlanRequest(BaseModel):
    plan: str


@router.post("/billing/plan")
def change_plan(req: PlanRequest, owner: str = Depends(_owner)) -> dict:
    try:
        made = billing.buy_plan(_api().database, owner, req.plan, _api().settings.seller_state)
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    analytics.track("billing.plan_changed", owner, {"plan": req.plan, "currency": made["currency"]})
    return {**view(owner), "invoice": made}


class TopupRequest(BaseModel):
    credits: float


@router.post("/billing/topup")
def top_up(req: TopupRequest, owner: str = Depends(_owner)) -> dict:
    try:
        made = billing.buy_topup(_api().database, owner, req.credits, _api().settings.seller_state)
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    analytics.track("billing.topped_up", owner, {"credits": req.credits, "currency": made["currency"]})
    return {**view(owner), "invoice": made}


@router.get("/billing/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: int, owner: str = Depends(_owner)) -> HTMLResponse:
    found = billing.invoice(_api().database, owner, invoice_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That invoice is not yours or does not exist.")
    return HTMLResponse(billing.invoice_html(found, seller()))
