"""G3: billing (routes). Owner only (G2's role table keeps Editors and
Reviewers off /billing). Needs `golive.g3`; with it off the Billing page
keeps its plain "no billing in this build" view.

    GET  /billing                  plan, credits (granted, used, left, about N minutes), plans,
                                   top-ups, provider (test mode), billing details, invoices
    PUT  /billing/details          {country, legal_name?, gstin?, state_code?}
    POST /billing/plan             {plan}: through the fake provider, an invoice; through a real
                                   one, {checkout} (Stripe's page url, or a Razorpay order)
    POST /billing/topup            {credits}: the same
    POST /billing/razorpay/verify  {order_id, payment_id, signature}: checkout.js's signed payment
    GET  /billing/invoices/{id}    the invoice as a printable HTML page

Run 4 item 4b: every paid purchase (the fake provider at once, Razorpay's
signed payment, a Stripe or Razorpay webhook) emails a receipt and the tax
invoice, the invoice with its PDF attached (`paid_emails`).

Item 7, public (no session, no CSRF header; the signature is the check):
    POST /billing/webhooks/stripe     Stripe-Signature over the raw body; 400 when bad
    POST /billing/webhooks/razorpay   X-Razorpay-Signature over the raw body; 400 when bad
Admins only:
    POST /admin/billing/refund     {owner, invoice_id}: in full, credits taken back
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import analytics, billing
from app.billing import gst, webhooks
from app.billing.providers import (
    WebhookRejected,
    provider_for,
    real_razorpay,
    real_stripe,
)

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


def _provider(owner: str):
    """The provider for the owner's billing country: real when its keys are set."""
    return provider_for(billing.account(_api().database, owner)["country"], _api().settings)


def view(owner: str) -> dict:
    db = _api().database
    acct = billing.account(db, owner)
    got = billing.credits(db, owner, spent_since(owner))
    per_minute = analytics.cost_per_exported_minute(db)["per_minute"]
    # "About N minutes" only when a cost per exported minute has been measured; no guess otherwise.
    minutes = int(got["left"] / per_minute) if per_minute and got["left"] > 0 else (0 if per_minute else None)
    provider = provider_for(acct["country"], _api().settings)
    return {
        "account": acct, "credits": {**got, "minutes": minutes},
        "plan": next((p for p in billing.plans_for(acct["country"]) if p["plan_id"] == acct["plan"]), None),
        "plans": billing.plans_for(acct["country"]), "topups": billing.topups_for(acct["country"]),
        "provider": {"name": provider.name, "label": provider.label, "test_mode": provider.test_mode},
        "trial_credits": billing.TRIAL_CREDITS, "invoices": billing.invoices(db, owner),
        "states": [{"code": k, "name": v} for k, v in sorted(gst.STATES.items(), key=lambda kv: kv[1])],
    }


def paid_emails(owner: str, inv: dict) -> None:
    """The receipt and the tax invoice (with its PDF) for a paid invoice. Never raises:
    the payment is done either way, and the log says what failed."""
    api = _api()
    try:
        from app.billing import pdf
        from app.notify import email as email_mod, templates
        to = email_mod.person_address(api.database, owner)
        if not to:
            api.log.warning("invoice %s: no address for its owner, so no receipt or invoice email", inv["number"])
            return
        data = templates.invoice_data(inv, seller(), gst.STATES)
        got = billing.bought(api.database, inv["id"])
        plan = billing.PLANS.get(got.get("plan") or "")
        extra = {"plan": plan.name} if plan else {"credits": f"{float(got.get('credits') or 0):g}"}
        url = api.settings.public_url
        api.email_sender.send(templates.email("receipt", to, public_url=url, owner=owner, **data, **extra))
        attached = email_mod.Attachment(f"{inv['number']}.pdf", "application/pdf", pdf.invoice_pdf(inv, seller()))
        api.email_sender.send(templates.email("invoice", to, public_url=url, owner=owner, attachments=(attached,), **data))
    except Exception:  # noqa: BLE001
        api.log.exception("receipt and invoice emails for %s", inv.get("number"))


def _paid_by_webhook(got: dict) -> dict:
    """A webhook that granted a purchase: its emails (the route's answer stays the same)."""
    if got.get("handled") and got.get("invoice"):
        inv = billing.invoice_by_number(_api().database, got["invoice"])
        if inv is not None:
            paid_emails(inv["owner"], inv)
    return got


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
        made = billing.buy_plan(_api().database, owner, req.plan, _api().settings.seller_state, _provider(owner))
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if made.get("pending"):
        return {**view(owner), "checkout": made["checkout"]}
    analytics.track("billing.plan_changed", owner, {"plan": req.plan, "currency": made["currency"]})
    paid_emails(owner, made)
    return {**view(owner), "invoice": made}


class TopupRequest(BaseModel):
    credits: float


@router.post("/billing/topup")
def top_up(req: TopupRequest, owner: str = Depends(_owner)) -> dict:
    try:
        made = billing.buy_topup(_api().database, owner, req.credits, _api().settings.seller_state, _provider(owner))
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if made.get("pending"):
        return {**view(owner), "checkout": made["checkout"]}
    analytics.track("billing.topped_up", owner, {"credits": req.credits, "currency": made["currency"]})
    paid_emails(owner, made)
    return {**view(owner), "invoice": made}


@router.get("/billing/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: int, owner: str = Depends(_owner)) -> HTMLResponse:
    found = billing.invoice(_api().database, owner, invoice_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That invoice is not yours or does not exist.")
    return HTMLResponse(billing.invoice_html(found, seller()))


class RazorpayPaid(BaseModel):
    order_id: str
    payment_id: str
    signature: str


@router.post("/billing/razorpay/verify")
def razorpay_verify(req: RazorpayPaid, owner: str = Depends(_owner)) -> dict:
    """checkout.js's signed payment: a good signature for an order this owner opened grants it (once;
    the `payment.captured` webhook for the same order then grants nothing)."""
    api = _api()
    provider = real_razorpay(api.settings)
    rec = billing.pending(api.database, "razorpay", req.order_id) if provider else None
    if provider is None or rec is None or rec["owner"] != owner:
        raise HTTPException(status_code=404, detail="That payment is not one we opened.")
    if not provider.verify_payment(req.order_id, req.payment_id, req.signature):
        raise HTTPException(status_code=400, detail="That payment could not be verified. Nothing was granted.")
    made = billing.fulfil(api.database, "razorpay", req.order_id, req.payment_id, api.settings.seller_state,
                          test_mode=provider.test_mode)
    if made is not None:
        paid_emails(owner, made)
    return {**view(owner), "invoice": made}


@router.post("/billing/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    api = _api()
    provider = real_stripe(api.settings)
    if provider is None:
        raise HTTPException(status_code=404, detail="Not found")
    payload = await request.body()
    try:
        event = provider.verify_webhook(payload, request.headers.get("stripe-signature"))
    except WebhookRejected:
        raise HTTPException(status_code=400, detail="Bad signature.") from None
    got = await asyncio.to_thread(webhooks.handle_stripe, api.database, provider, event, api.settings.seller_state)
    return await asyncio.to_thread(_paid_by_webhook, got)


@router.post("/billing/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    api = _api()
    provider = real_razorpay(api.settings)
    if provider is None or not provider.webhook_secret:
        raise HTTPException(status_code=404, detail="Not found")
    payload = await request.body()
    try:
        event = provider.verify_webhook(payload, request.headers.get("x-razorpay-signature"))
    except WebhookRejected:
        raise HTTPException(status_code=400, detail="Bad signature.") from None
    got = await asyncio.to_thread(webhooks.handle_razorpay, api.database, provider, event,
                                  request.headers.get("x-razorpay-event-id"), api.settings.seller_state)
    return await asyncio.to_thread(_paid_by_webhook, got)


class RefundRequest(BaseModel):
    owner: str
    invoice_id: int
    reason: str = ""          # item 10: kept in the audit trail


@router.post("/admin/billing/refund")
def admin_refund(req: RefundRequest, request: Request) -> dict:
    """Refund an invoice in full (admins only): the provider gives the money back, the credits go."""
    from app.analytics_api import is_admin
    api = _api()
    user = api.signed_in_user(request)
    if api.settings.auth_mode != "off" and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    if not is_admin(user):
        raise HTTPException(status_code=404, detail="Not found")
    found = billing.invoice(api.database, req.owner, req.invoice_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That invoice is not theirs or does not exist.")
    from app.billing.providers import provider_named
    try:
        done = billing.refund(api.database, req.owner, req.invoice_id, provider_named(found["provider"], api.settings))
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    from app import admin
    admin.audit(api.database, user, "refund", req.owner, req.reason,
                {"invoice": found["number"], "refund_id": done["refund_id"], "credits_taken_back": done["credits_taken_back"]})
    analytics.track("billing.refunded", req.owner, {"invoice": found["number"], "currency": found["currency"]})
    return done
