"""G3: billing behind interfaces. Plans with monthly credits, top-ups, free
trial credits, a hard stop when credits run out, GST invoices.

Credits are USD-equivalent: one credit pays for $1 of vendor spend as the
ledger records it. What an owner has left is everything granted (the trial,
each month's plan credits, top-ups) minus everything spent since their
billing account began (the ledger, all their work). Credits are granted as
rows in `credit_grants`; a month's plan credits are granted the first time
the account is read in that month. Unused plan credits lapse when their month ends and top-ups after 12 months (`balance`).

    account(db, owner) -> dict                       made on first read, with the trial
    credits(db, owner, spent_since) -> dict          granted, used, left, share
    set_details(db, owner, country=, legal_name=, gstin=, state_code=)
    buy_plan(db, owner, plan_id, provider) / buy_topup(db, owner, credits, provider) -> invoice
    invoices(db, owner) / invoice(db, owner, invoice_id) / invoice_html(invoice)

    fulfil(db, provider, reference, payment_ref, ...) -> invoice | None     a confirmed real payment, once
    refund(db, owner, invoice_id) -> dict            in full, credits taken back

Payments go through `providers.BillingProvider`: fake (test mode, paid at
once) unless a provider's keys are set; a real one returns a pending
checkout and grants only on a verified webhook (item 7). Nothing in this
module talks to a network itself.
"""
from __future__ import annotations

import html
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.billing import gst
from app.billing.providers import BillingProvider, Checkout, ProviderError, minor, provider_for, provider_named
from app.errors import NonRetryableError
from app.timefmt import now_iso
from app.usage import SpendCeilingReached

log = logging.getLogger("voltage.billing")

# Every price, plan and credit amount lives in one file for the owner to set: app/billing/prices.py.
from app.billing.prices import INR_PER_USD, PLANS, TOPUP_MARKUP, TOPUP_MONTHS, TOPUPS, TRIAL_CREDITS, Plan  # noqa: E402,F401


class BillingError(ValueError):
    """A request that cannot be done, with a sentence to show."""


class CreditsUsedUp(SpendCeilingReached):
    """G3: the owner's credits are used up; paid work stops (the spend guard's hard ceiling)."""

    scope = "credits"

    def __init__(self, used: float, granted: float) -> None:
        self.spent, self.ceiling = used, granted
        NonRetryableError.__init__(self, "Your credits are used up, so paid steps are paused. "
                                         "Top up or pick a plan on the Billing page to carry on.")


# Item 7: real payments keep their bookkeeping in `meta` (no new table):
# what an open checkout buys, that it was granted, what an invoice granted,
# that it was refunded, and which webhook events were handled.
def _pending_key(provider: str, reference: str) -> str:
    return f"billing_pending:{provider}:{reference}"


def _paid_key(provider: str, reference: str) -> str:
    return f"billing_paid:{provider}:{reference}"


def _bought_key(invoice_id: int) -> str:
    return f"billing_bought:{invoice_id}"


def _refund_key(invoice_id: int) -> str:
    return f"billing_refund:{invoice_id}"


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _row(c, owner: str):
    return c.execute("SELECT * FROM billing_accounts WHERE owner = ?", (owner,)).fetchone()


def _grant_in(c, owner: str, kind: str, credits: float, period: str | None, reference: str) -> None:
    c.execute("INSERT INTO credit_grants (owner, kind, credits, period, reference, at) VALUES (?, ?, ?, ?, ?, ?)",
              (owner, kind, float(credits), period, reference, now_iso()))


def _account_dict(r) -> dict:
    return {"owner": r["owner"], "plan": r["plan"], "country": r["country"], "legal_name": r["legal_name"],
            "gstin": r["gstin"], "state_code": r["state_code"], "created_at": r["created_at"]}


def has_account(db, owner: str) -> bool:
    """Billing applies to an owner once they have an account: made at a new
    owner's first sign-in, or when an existing owner first opens Billing."""
    with db.tx() as c:
        return _row(c, owner) is not None


def account(db, owner: str, now: datetime | None = None) -> dict:
    """The owner's billing account, made the first time with the free trial's
    credits; this month's plan credits are granted on the first read of a month."""
    with db.tx() as c:
        r = _row(c, owner)
        if r is None:
            c.execute("INSERT INTO billing_accounts (owner, plan, country, legal_name, gstin, state_code, created_at) "
                      "VALUES (?, NULL, NULL, '', '', NULL, ?)", (owner, now_iso()))
            _grant_in(c, owner, "trial", TRIAL_CREDITS, None, "Free trial")
            r = _row(c, owner)
        plan = PLANS.get(r["plan"] or "")
        if plan is not None:
            period = _month(now)
            if not c.execute("SELECT 1 FROM credit_grants WHERE owner = ? AND kind = 'plan' AND period = ?",
                             (owner, period)).fetchone():
                _grant_in(c, owner, "plan", plan.credits, period, f"{plan.name} plan, {period}")
        return _account_dict(r)


def expires_at(kind: str, period: str | None, at: str) -> str | None:
    """When a grant's unused credits lapse (decision 0, 2026-10-22): a month's
    plan credits at the end of that month, a top-up 12 months after it was
    bought; the free trial does not lapse."""
    if kind == "plan" and period:
        year, month = (int(x) for x in period.split("-"))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return f"{year:04d}-{month:02d}-01T00:00:00.000Z"
    if kind == "topup":
        year, rest = int(at[:4]), at[4:]
        months = TOPUP_MONTHS
        month = int(rest[1:3]) + months
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
        day = min(int(rest[4:6]), 28)
        return f"{year:04d}-{month:02d}-{day:02d}{at[10:]}"
    return None


def balance(grants: list[dict], spent_since: Callable[[str], float], start: str, now: str) -> dict:
    """Spend the ledger against the grants in time order, soonest to lapse
    first, and let what is left of a grant lapse at its expiry. Returns used,
    left, lapsed and each grant's own remainder (`left`, `expires_at`)."""
    for g in grants:
        g["expires_at"] = expires_at(g["kind"], g["period"], g["at"])
        g["left"] = 0.0
    points = sorted({start, now, *(g["at"] for g in grants if start < g["at"] < now),
                     *(g["expires_at"] for g in grants if g["expires_at"] and start < g["expires_at"] < now)})
    since = {p: float(spent_since(p)) for p in points}
    active: list[dict] = []
    lapsed = debt = 0.0
    for i, point in enumerate(points):
        for g in grants:
            if g["at"] <= point and g not in active and not g.get("_done"):
                g["_done"] = True
                if float(g["credits"]) < 0:          # a refund takes credits back: owed from what is left
                    debt += -float(g["credits"])
                    for held in sorted(active, key=lambda h: h["expires_at"] or "9999"):
                        take = min(debt, held["left"])
                        held["left"] -= take
                        debt -= take
                    continue
                g["left"] = float(g["credits"])
                active.append(g)
                if debt:
                    take = min(debt, g["left"])
                    g["left"] -= take
                    debt -= take
        for g in list(active):
            if g["expires_at"] and g["expires_at"] <= point:
                lapsed += g["left"]
                g["left"] = 0.0
                active.remove(g)
        # Spend from this point to the next (the last runs to now and beyond: anything not yet counted).
        spend = since[point] - (since[points[i + 1]] if i + 1 < len(points) else 0.0)
        for g in sorted(active, key=lambda g: g["expires_at"] or "9999"):
            take = min(spend, g["left"])
            g["left"] -= take
            spend -= take
        debt += spend
    left = sum(g["left"] for g in active) - debt
    for g in grants:
        g.pop("_done", None)
        g["left"] = round(g["left"], 4)
    return {"used": round(since[start], 4), "left": round(left, 4), "lapsed": round(lapsed, 4)}


def credits(db, owner: str, spent_since: Callable[[str], float]) -> dict:
    """What is granted, used (the ledger since the account began), lapsed
    and left; `share` is used over granted (None when nothing was granted).
    Plan credits lapse at the month's end, top-ups after 12 months."""
    acct = account(db, owner)
    with db.tx() as c:
        rows = [dict(g) for g in c.execute("SELECT * FROM credit_grants WHERE owner = ? ORDER BY at, id", (owner,))]
    for r in rows:
        if r["at"] < acct["created_at"]:
            r["at"] = acct["created_at"]
    got = balance(rows, spent_since, acct["created_at"], now_iso())
    granted = sum(float(r["credits"]) for r in rows)
    grants = [{"kind": g["kind"], "credits": g["credits"], "period": g["period"], "reference": g["reference"], "at": g["at"],
               "expires_at": g["expires_at"], "left": g["left"]} for g in reversed(rows)][:20]
    return {"granted": round(granted, 4), "used": got["used"], "left": got["left"], "lapsed": got["lapsed"],
            "share": (got["used"] / granted) if granted > 0 else None, "grants": grants}


def can_spend(db, owner: str, spent_since: Callable[[str], float]) -> tuple[bool, dict]:
    got = credits(db, owner, spent_since)
    return got["left"] > 0, got


def set_details(db, owner: str, *, country: str | None, legal_name: str = "", gstin: str = "",
                state_code: str | None = None) -> dict:
    country = (country or "").strip().upper() or None
    if country is not None and (len(country) != 2 or not country.isalpha()):
        raise BillingError("Pick the country you are billed in.")
    gstin = (gstin or "").strip().upper()
    if gstin and country != "IN":
        raise BillingError("A GSTIN is for businesses billed in India.")
    if gstin and not gst.valid_gstin(gstin):
        raise BillingError("That GSTIN does not look right. It has 15 characters, like 29ABCDE1234F1Z5.")
    if gstin:
        state_code = gst.state_of(gstin)            # the GSTIN says where the business is registered
    if state_code is not None and state_code not in gst.STATES:
        raise BillingError("Pick the state you are billed in.")
    account(db, owner)
    with db.tx() as c:
        c.execute("UPDATE billing_accounts SET country = ?, legal_name = ?, gstin = ?, state_code = ? WHERE owner = ?",
                  (country, " ".join((legal_name or "").split())[:200], gstin, state_code if country == "IN" else None, owner))
        return _account_dict(_row(c, owner))


def price(plan_or_usd: Plan | float, country: str | None) -> tuple[float, str]:
    """(amount, currency) for the buyer's country: INR in India, USD elsewhere."""
    india = (country or "").upper() == "IN"
    if isinstance(plan_or_usd, Plan):
        return (plan_or_usd.inr, "INR") if india else (plan_or_usd.usd, "USD")
    usd = float(plan_or_usd)
    return (round(usd * INR_PER_USD), "INR") if india else (round(usd, 2), "USD")


def topup_price(credits_: float, country: str | None) -> tuple[float, str]:
    return price(round(credits_ * TOPUP_MARKUP, 2), country)


def _invoice_in(c, owner: str, acct: dict, kind: str, description: str, subtotal: float, currency: str,
                checkout, seller_state: str) -> dict:
    tax = gst.split(subtotal, acct["country"], acct["state_code"], seller_state)
    n = int(c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]) + 1
    number = f"VLT-{datetime.now(timezone.utc).strftime('%Y%m')}-{n:05d}"
    c.execute("INSERT INTO invoices (number, owner, provider, checkout_id, kind, description, currency, subtotal, cgst, sgst, igst, "
              "total, tax_kind, country, state_code, gstin, legal_name, test_mode, issued_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (number, owner, checkout.provider, checkout.checkout_id, kind, description, currency, tax.subtotal, tax.cgst, tax.sgst,
               tax.igst, tax.total, tax.kind, acct["country"], acct["state_code"], acct["gstin"], acct["legal_name"],
               int(checkout.test_mode), now_iso()))
    return _invoice(c.execute("SELECT * FROM invoices WHERE id = last_insert_rowid()").fetchone())


def _pay(provider: BillingProvider, owner: str, description: str, amount: float, currency: str, acct: dict, seller_state: str):
    """Charge the total with tax through the provider; a decline is a sentence."""
    total = gst.split(amount, acct["country"], acct["state_code"], seller_state).total
    checkout = provider.checkout(owner, description, total, currency)
    if checkout.status != "paid":
        raise BillingError("The payment did not go through. Nothing was charged; try again.")
    return checkout


def _hosted(provider) -> bool:
    return bool(getattr(provider, "hosted", False))


def _start(db, provider, owner: str, item: dict, description: str, amount: float, currency: str, acct: dict,
           seller_state: str) -> dict:
    """Item 7: open a real payment (Stripe's hosted page, a Razorpay order) and
    remember what it buys; nothing is granted until the provider confirms it."""
    total = gst.split(amount, acct["country"], acct["state_code"], seller_state).total
    purchase = uuid.uuid4().hex
    try:
        checkout = provider.start(owner, description, total, currency, {"owner": owner, "purchase": purchase, **item},
                                  idempotency_key=f"checkout-{purchase}")
    except ProviderError as exc:
        log.warning("%s checkout failed: %s", provider.name, exc)
        raise BillingError("We could not open the payment page. Nothing was charged; try again.") from None
    record = {"owner": owner, "purchase": purchase, **item, "description": description, "subtotal": amount,
              "currency": currency, "total": total}
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                  (_pending_key(provider.name, checkout.checkout_id), json.dumps(record)))
    return {"pending": True, "checkout": {"provider": provider.name, "checkout_id": checkout.checkout_id, "url": checkout.url,
                                          "client": checkout.client, "total": total, "currency": currency,
                                          "test_mode": checkout.test_mode}}


def _complete(c, owner: str, acct: dict, item: dict, description: str, amount: float, currency: str, checkout,
              seller_state: str, now: datetime | None = None) -> dict:
    """Grant what a paid purchase buys and issue its invoice (inside the caller's transaction)."""
    granted = 0.0
    if item["kind"] == "plan":
        plan = PLANS[item["plan"]]
        c.execute("UPDATE billing_accounts SET plan = ? WHERE owner = ?", (plan.plan_id, owner))
        period = _month(now)
        # Changing plan this month: the new plan's credits for this month, once per plan.
        if not c.execute("SELECT 1 FROM credit_grants WHERE owner = ? AND kind = 'plan' AND period = ? AND reference LIKE ?",
                         (owner, period, f"{plan.name} plan%")).fetchone():
            _grant_in(c, owner, "plan", plan.credits, period, f"{plan.name} plan, {period}")
            granted = plan.credits
    else:
        _grant_in(c, owner, "topup", float(item["credits"]), None, description)
        granted = float(item["credits"])
    inv = _invoice_in(c, owner, acct, item["kind"], description, amount, currency, checkout, seller_state)
    # What a refund takes back: the credits this purchase granted, and the plan it started.
    c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
              (_bought_key(inv["id"]), json.dumps({"credits": granted, "plan": item.get("plan")})))
    return inv


def buy_plan(db, owner: str, plan_id: str, seller_state: str, provider: BillingProvider | None = None,
             now: datetime | None = None) -> dict:
    """The invoice (a fake provider pays at once), or {"pending": True,
    "checkout": ...} when a real provider takes the payment first."""
    plan = PLANS.get(plan_id)
    if plan is None:
        raise BillingError("That plan is not one we offer.")
    acct = account(db, owner, now)
    if acct["plan"] == plan_id:
        raise BillingError(f"You are already on {plan.name}.")
    provider = provider or provider_for(acct["country"])
    amount, currency = price(plan, acct["country"])
    description = f"{plan.name} plan, {_month(now)}: {plan.credits:g} credits a month"
    item = {"kind": "plan", "plan": plan_id}
    if _hosted(provider):
        return _start(db, provider, owner, item, description, amount, currency, acct, seller_state)
    checkout = _pay(provider, owner, description, amount, currency, acct, seller_state)
    with db.tx() as c:
        return _complete(c, owner, acct, item, description, amount, currency, checkout, seller_state, now)


def buy_topup(db, owner: str, credits_: float, seller_state: str, provider: BillingProvider | None = None) -> dict:
    if credits_ not in TOPUPS:
        raise BillingError(f"Top-ups come in {', '.join(str(t) for t in TOPUPS)} credits.")
    acct = account(db, owner)
    provider = provider or provider_for(acct["country"])
    amount, currency = topup_price(credits_, acct["country"])
    description = f"Top-up: {credits_:g} credits"
    item = {"kind": "topup", "credits": float(credits_)}
    if _hosted(provider):
        return _start(db, provider, owner, item, description, amount, currency, acct, seller_state)
    checkout = _pay(provider, owner, description, amount, currency, acct, seller_state)
    with db.tx() as c:
        return _complete(c, owner, acct, item, description, amount, currency, checkout, seller_state)


def pending(db, provider_name: str, reference: str) -> dict | None:
    """What a real checkout (a Stripe session id, a Razorpay order id) was opened to buy."""
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (_pending_key(provider_name, reference),)).fetchone()
    return json.loads(row[0]) if row else None


def fulfil(db, provider_name: str, reference: str, payment_ref: str, seller_state: str, *, test_mode: bool,
           paid_minor: int | None = None, paid_currency: str | None = None, now: datetime | None = None) -> dict | None:
    """Item 7: a confirmed payment grants what it bought, once. `reference` is
    the checkout (session or order) id, `payment_ref` what a refund needs (the
    payment intent, the payment id). None when it is not ours, does not match
    what was asked, or was granted already (a retried webhook, or Razorpay's
    signed payment and its webhook both arriving)."""
    rec = pending(db, provider_name, reference)
    if rec is None:
        log.warning("%s payment for %s: no checkout of ours; nothing granted", provider_name, reference)
        return None
    if paid_minor is not None and (paid_minor != minor(rec["total"]) or (paid_currency or "").upper() != rec["currency"]):
        log.error("%s payment for %s: paid %s %s, asked %s %s; nothing granted", provider_name, reference, paid_minor,
                  paid_currency, minor(rec["total"]), rec["currency"])
        return None
    owner = rec["owner"]
    acct = account(db, owner, now)
    item = {k: rec[k] for k in ("kind", "plan", "credits") if k in rec}
    checkout = Checkout(payment_ref, provider_name, "paid", rec["total"], rec["currency"], test_mode)
    with db.tx() as c:
        claimed = c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                            (_paid_key(provider_name, reference), json.dumps({"payment": payment_ref, "at": now_iso()})))
        if claimed.rowcount == 0:
            return None
        return _complete(c, owner, acct, item, rec["description"], rec["subtotal"], rec["currency"], checkout, seller_state, now)


def refund(db, owner: str, invoice_id: int, provider: BillingProvider | None = None) -> dict:
    """Item 7: refund an invoice in full through the provider that took it and
    take back the credits it granted (and the plan it started). Once only."""
    inv = invoice(db, owner, invoice_id)
    if inv is None:
        raise BillingError("That invoice is not yours or does not exist.")
    provider = provider or provider_named(inv["provider"])
    with db.tx() as c:
        claimed = c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (_refund_key(invoice_id), now_iso()))
        if claimed.rowcount == 0:
            raise BillingError("That payment was refunded already.")
        row = c.execute("SELECT value FROM meta WHERE key = ?", (_bought_key(invoice_id),)).fetchone()
    bought = json.loads(row[0]) if row else {"credits": 0.0, "plan": None}
    try:
        refund_id = provider.refund(inv["checkout_id"], inv["total"], inv["currency"], idempotency_key=f"refund-{inv['number']}")
    except ProviderError as exc:
        log.warning("%s refund of %s failed: %s", provider.name, inv["number"], exc)
        with db.tx() as c:
            c.execute("DELETE FROM meta WHERE key = ?", (_refund_key(invoice_id),))
        raise BillingError("The refund did not go through. Nothing changed; try again.") from None
    taken = float(bought.get("credits") or 0.0)
    with db.tx() as c:
        c.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps({"refund": refund_id, "at": now_iso()}), _refund_key(invoice_id)))
        if taken:
            _grant_in(c, owner, "refund", -taken, None, f"Refund of {inv['number']}")
        if bought.get("plan"):
            c.execute("UPDATE billing_accounts SET plan = NULL WHERE owner = ? AND plan = ?", (owner, bought["plan"]))
    return {"invoice": inv, "refund_id": refund_id, "credits_taken_back": taken}


def admin_grant(db, owner: str, credits_: float, reason: str) -> dict:
    """Item 10: credits an admin gives (kind `admin`, never lapse), or takes back
    as a credit reversal (a negative `refund` grant, owed from what is left)."""
    if not credits_ or abs(float(credits_)) > 10_000:
        raise BillingError("Give between 0.01 and 10,000 credits.")
    account(db, owner)
    with db.tx() as c:
        if credits_ > 0:
            _grant_in(c, owner, "admin", float(credits_), None, f"Given by Voltage: {reason}"[:200])
        else:
            _grant_in(c, owner, "refund", float(credits_), None, f"Credit reversal: {reason}"[:200])
        gid = int(c.execute("SELECT MAX(id) FROM credit_grants WHERE owner = ?", (owner,)).fetchone()[0])
    return {"grant_id": gid, "credits": float(credits_)}


def refunded(db, invoice_id: int) -> bool:
    with db.tx() as c:
        return c.execute("SELECT 1 FROM meta WHERE key = ?", (_refund_key(invoice_id),)).fetchone() is not None


def _invoice(r) -> dict:
    d = dict(r)
    d["test_mode"] = bool(d.get("test_mode"))
    return d


def invoices(db, owner: str) -> list[dict]:
    with db.tx() as c:
        return [_invoice(r) for r in c.execute("SELECT * FROM invoices WHERE owner = ? ORDER BY id DESC", (owner,))]


def invoice(db, owner: str, invoice_id: int) -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM invoices WHERE id = ? AND owner = ?", (invoice_id, owner)).fetchone()
    return _invoice(r) if r else None


def _money(amount: float, currency: str) -> str:
    return f"₹{amount:,.2f}" if currency == "INR" else f"${amount:,.2f}"


def invoice_html(inv: dict, seller: dict) -> str:
    """A printable tax invoice. In test mode it says so at the top, and that no money moved."""
    e = html.escape
    m = lambda v: e(_money(float(v), inv["currency"]))  # noqa: E731
    tax_rows = ""
    if inv["tax_kind"] == "intra":
        tax_rows = f"<tr><td>CGST 9%</td><td class=n>{m(inv['cgst'])}</td></tr><tr><td>SGST 9%</td><td class=n>{m(inv['sgst'])}</td></tr>"
    elif inv["tax_kind"] == "inter":
        tax_rows = f"<tr><td>IGST 18%</td><td class=n>{m(inv['igst'])}</td></tr>"
    else:
        tax_rows = "<tr><td>GST 0% (export of services)</td><td class=n>" + m(0) + "</td></tr>"
    place = gst.STATES.get(inv["state_code"] or "", inv["country"] or "Outside India")
    test = ("<p class=test>Test mode. No money moved; this invoice is a sample of what a real one will look like.</p>"
            if inv["test_mode"] else "")
    buyer = e(inv["legal_name"] or inv["owner"])
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>Invoice {e(inv['number'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;color:#0B0B0C;background:#fff;max-width:720px;margin:32px auto;padding:0 16px}}
h1{{font-size:26px;margin:0 0 4px}}table{{width:100%;border-collapse:collapse;margin:16px 0}}td,th{{padding:8px 0;border-bottom:1px solid #DEDED6;text-align:left}}
.n{{text-align:right}}.test{{border:1.5px solid #0B0B0C;background:#FFB020;padding:8px 12px;font-weight:600}}.muted{{color:#5C5C58}}</style></head><body>
{test}<h1>Tax invoice</h1><p class=muted>{e(inv['number'])} · issued {e(inv['issued_at'][:10])} · paid through {e(inv['provider'].title())} ({e(inv['checkout_id'])})</p>
<p><strong>From</strong><br>{e(seller['name'])}<br>GSTIN {e(seller['gstin'] or 'not set yet')}<br>{e(gst.STATES.get(seller['state'], seller['state']))}</p>
<p><strong>To</strong><br>{buyer}<br>{('GSTIN ' + e(inv['gstin'])) if inv['gstin'] else 'No GSTIN'}<br>Place of supply: {e(place)}</p>
<table><tr><th>Description</th><th class=n>Amount</th></tr><tr><td>{e(inv['description'])}<br><span class=muted>SAC {gst.SAC}</span></td><td class=n>{m(inv['subtotal'])}</td></tr>
{tax_rows}<tr><th>Total</th><th class=n>{m(inv['total'])}</th></tr></table></body></html>"""


def plans_for(country: str | None) -> list[dict]:
    out = []
    for p in PLANS.values():
        amount, currency = price(p, country)
        out.append({**asdict(p), "price": amount, "currency": currency})
    return out


def topups_for(country: str | None) -> list[dict]:
    return [{"credits": t, "price": topup_price(t, country)[0], "currency": topup_price(t, country)[1]} for t in TOPUPS]


