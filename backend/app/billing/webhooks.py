"""Item 7: what a verified payment webhook does. The routes (app/billing_api.py)
check the signature on the raw body first; these only see good events.

    handle_stripe(db, provider, event, seller_state) -> dict
        checkout.session.completed (paid) and checkout.session.async_payment_succeeded
    handle_razorpay(db, provider, event, event_id, seller_state) -> dict
        payment.captured

Every event id is remembered (`meta`, `billing_event:<provider>:<id>`), so a
retried delivery answers "duplicate" and grants nothing; the grant itself is
also once per checkout (`billing.fulfil`), so two different events for one
payment still grant once. Anything else is acknowledged and ignored.
"""
from __future__ import annotations

from app import billing
from app.timefmt import now_iso

STRIPE_PAID = ("checkout.session.completed", "checkout.session.async_payment_succeeded")


def _event_key(provider: str, event_id: str) -> str:
    return f"billing_event:{provider}:{event_id}"


def seen(db, provider: str, event_id: str) -> bool:
    with db.tx() as c:
        return c.execute("SELECT 1 FROM meta WHERE key = ?", (_event_key(provider, event_id),)).fetchone() is not None


def _remember(db, provider: str, event_id: str) -> None:
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (_event_key(provider, event_id), now_iso()))


def handle_stripe(db, provider, event: dict, seller_state: str) -> dict:
    event_id = str(event.get("id") or "")
    if not event_id:
        return {"ok": True, "handled": False}
    if seen(db, "stripe", event_id):
        return {"ok": True, "duplicate": True}
    granted = None
    session = (event.get("data") or {}).get("object") or {}
    if event.get("type") in STRIPE_PAID and session.get("payment_status") == "paid":
        granted = billing.fulfil(db, "stripe", str(session.get("id") or ""), str(session.get("payment_intent") or ""),
                                 seller_state, test_mode=not bool(event.get("livemode")),
                                 paid_minor=session.get("amount_total"), paid_currency=session.get("currency"))
    _remember(db, "stripe", event_id)
    return {"ok": True, "handled": granted is not None, "invoice": granted["number"] if granted else None}


def handle_razorpay(db, provider, event: dict, event_id: str | None, seller_state: str) -> dict:
    payment = (((event.get("payload") or {}).get("payment") or {}).get("entity")) or {}
    event_id = event_id or f"{event.get('event')}:{payment.get('id')}"
    if seen(db, "razorpay", event_id):
        return {"ok": True, "duplicate": True}
    granted = None
    if event.get("event") == "payment.captured" and payment.get("order_id"):
        granted = billing.fulfil(db, "razorpay", str(payment["order_id"]), str(payment.get("id") or ""), seller_state,
                                 test_mode=provider.test_mode, paid_minor=payment.get("amount"),
                                 paid_currency=payment.get("currency"))
    _remember(db, "razorpay", event_id)
    return {"ok": True, "handled": granted is not None, "invoice": granted["number"] if granted else None}
