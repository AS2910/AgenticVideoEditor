"""G3: billing behind interfaces. Plans with monthly credits, top-ups, free
trial credits, a hard stop when credits run out, GST invoices.

Credits are USD-equivalent: one credit pays for $1 of vendor spend as the
ledger records it. What an owner has left is everything granted (the trial,
each month's plan credits, top-ups) minus everything spent since their
billing account began (the ledger, all their work). Credits are granted as
rows in `credit_grants`; a month's plan credits are granted the first time
the account is read in that month (they carry over; see DECISIONS.md).

    account(db, owner) -> dict                       made on first read, with the trial
    credits(db, owner, spent_since) -> dict          granted, used, left, share
    set_details(db, owner, country=, legal_name=, gstin=, state_code=)
    buy_plan(db, owner, plan_id, provider) / buy_topup(db, owner, credits, provider) -> invoice
    invoices(db, owner) / invoice(db, owner, invoice_id) / invoice_html(invoice)

Payments go through `providers.BillingProvider`; both providers are fake
(test mode). Nothing here talks to a network.
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

from app.billing import gst
from app.billing.providers import BillingProvider, provider_for
from app.errors import NonRetryableError
from app.timefmt import now_iso
from app.usage import SpendCeilingReached

TRIAL_CREDITS = 5.0
INR_PER_USD = 84.0
TOPUP_MARKUP = 1.2           # a top-up credit costs $1.20 (the margin on vendor cost)
TOPUPS = (10, 25, 50)


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    credits: float           # included each month
    usd: float               # price a month
    inr: float
    blurb: str


PLANS = {p.plan_id: p for p in (
    Plan("starter", "Starter", 15.0, 19.0, 1599.0, "For one person trying a few videos a month."),
    Plan("studio", "Studio", 50.0, 59.0, 4999.0, "For a small team shipping every week."),
    Plan("agency", "Agency", 160.0, 179.0, 14999.0, "For agencies running campaigns for clients."),
)}


class BillingError(ValueError):
    """A request that cannot be done, with a sentence to show."""


class CreditsUsedUp(SpendCeilingReached):
    """G3: the owner's credits are used up; paid work stops (the spend guard's hard ceiling)."""

    scope = "credits"

    def __init__(self, used: float, granted: float) -> None:
        self.spent, self.ceiling = used, granted
        NonRetryableError.__init__(self, "Your credits are used up, so paid steps are paused. "
                                         "Top up or pick a plan on the Billing page to carry on.")


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


def credits(db, owner: str, spent_since: Callable[[str], float]) -> dict:
    """What is granted, used (the ledger since the account began) and left;
    `share` is used over granted (None when nothing was granted)."""
    acct = account(db, owner)
    with db.tx() as c:
        granted = float(c.execute("SELECT COALESCE(SUM(credits), 0) FROM credit_grants WHERE owner = ?", (owner,)).fetchone()[0])
        grants = [{"kind": g["kind"], "credits": g["credits"], "period": g["period"], "reference": g["reference"], "at": g["at"]}
                  for g in c.execute("SELECT * FROM credit_grants WHERE owner = ? ORDER BY id DESC LIMIT 20", (owner,))]
    used = round(float(spent_since(acct["created_at"])), 4)
    left = round(granted - used, 4)
    return {"granted": round(granted, 4), "used": used, "left": left,
            "share": (used / granted) if granted > 0 else None, "grants": grants}


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


def buy_plan(db, owner: str, plan_id: str, seller_state: str, provider: BillingProvider | None = None,
             now: datetime | None = None) -> dict:
    plan = PLANS.get(plan_id)
    if plan is None:
        raise BillingError("That plan is not one we offer.")
    acct = account(db, owner, now)
    if acct["plan"] == plan_id:
        raise BillingError(f"You are already on {plan.name}.")
    provider = provider or provider_for(acct["country"])
    amount, currency = price(plan, acct["country"])
    description = f"{plan.name} plan, {_month(now)}: {plan.credits:g} credits a month"
    checkout = _pay(provider, owner, description, amount, currency, acct, seller_state)
    with db.tx() as c:
        c.execute("UPDATE billing_accounts SET plan = ? WHERE owner = ?", (plan_id, owner))
        period = _month(now)
        # Changing plan this month: the new plan's credits for this month, once per plan.
        if not c.execute("SELECT 1 FROM credit_grants WHERE owner = ? AND kind = 'plan' AND period = ? AND reference LIKE ?",
                         (owner, period, f"{plan.name} plan%")).fetchone():
            _grant_in(c, owner, "plan", plan.credits, period, f"{plan.name} plan, {period}")
        return _invoice_in(c, owner, acct, "plan", description, amount, currency, checkout, seller_state)


def buy_topup(db, owner: str, credits_: float, seller_state: str, provider: BillingProvider | None = None) -> dict:
    if credits_ not in TOPUPS:
        raise BillingError(f"Top-ups come in {', '.join(str(t) for t in TOPUPS)} credits.")
    acct = account(db, owner)
    provider = provider or provider_for(acct["country"])
    amount, currency = topup_price(credits_, acct["country"])
    description = f"Top-up: {credits_:g} credits"
    checkout = _pay(provider, owner, description, amount, currency, acct, seller_state)
    with db.tx() as c:
        _grant_in(c, owner, "topup", credits_, None, description)
        return _invoice_in(c, owner, acct, "topup", description, amount, currency, checkout, seller_state)


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


