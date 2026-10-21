"""G3 store: GST splits (CGST+SGST in the seller's state, IGST across
states, zero-rated exports), GSTIN checks, the provider by country (both
fake, test mode), the trial and monthly plan credits, top-ups and invoices,
a declined payment changes nothing, the invoice page says test mode,
migration 0028 up and down."""
from datetime import datetime, timezone

import pytest

from app import billing
from app.billing import gst
from app.billing.providers import RAZORPAY, STRIPE, provider_for
from app.store import migrate
from app.store.db import Database


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "t.db")


def test_gst_splits():
    intra = gst.split(1000, "IN", "29", "29")
    assert (intra.cgst, intra.sgst, intra.igst, intra.total, intra.kind) == (90.0, 90.0, 0.0, 1180.0, "intra")
    inter = gst.split(1599, "IN", "27", "29")
    assert (inter.cgst, inter.sgst, inter.igst, inter.total, inter.kind) == (0.0, 0.0, 287.82, 1886.82, "inter")
    odd = gst.split(0.05, "IN", "29", "29")
    assert odd.cgst + odd.sgst == pytest.approx(round(0.05 * 0.18, 2))       # the halves add up to the whole
    export = gst.split(19, "US", None, "29")
    assert (export.tax, export.total, export.kind) == (0.0, 19.0, "export")


def test_gstin_and_provider_by_country():
    assert gst.valid_gstin("29ABCDE1234F1Z5") and gst.state_of("29abcde1234f1z5") == "29"
    assert not gst.valid_gstin("99ABCDE1234F1Z5") and not gst.valid_gstin("29ABCDE1234F1Y5") and not gst.valid_gstin("")
    assert provider_for("IN") is RAZORPAY and provider_for("us") is STRIPE and provider_for(None) is STRIPE
    assert RAZORPAY.test_mode and STRIPE.test_mode


def test_trial_plan_credits_topups_and_invoices(db):
    oct_ = datetime(2026, 10, 5, tzinfo=timezone.utc)
    acct = billing.account(db, "ana", oct_)
    assert acct["plan"] is None
    spent = {"usd": 0.0}
    got = billing.credits(db, "ana", lambda at: spent["usd"])
    assert (got["granted"], got["left"]) == (billing.TRIAL_CREDITS, billing.TRIAL_CREDITS)
    billing.set_details(db, "ana", country="IN", legal_name="Ana  Films", gstin="27ABCDE1234F1Z5")
    inv = billing.buy_plan(db, "ana", "studio", "29", now=oct_)
    assert inv["currency"] == "INR" and inv["provider"] == "razorpay" and inv["tax_kind"] == "inter" and inv["igst"] == round(4999 * 0.18, 2)
    assert inv["legal_name"] == "Ana Films" and inv["gstin"] == "27ABCDE1234F1Z5" and inv["test_mode"]
    billing.account(db, "ana", oct_)                                       # the same month: no second grant
    billing.account(db, "ana", datetime(2026, 11, 1, tzinfo=timezone.utc))   # a new month: the plan's credits again
    top = billing.buy_topup(db, "ana", 10, "29")
    assert top["subtotal"] == round(10 * billing.TOPUP_MARKUP * billing.INR_PER_USD)
    spent["usd"] = 20.0
    got = billing.credits(db, "ana", lambda at: spent["usd"])
    assert got["granted"] == billing.TRIAL_CREDITS + 50 + 50 + 10 and got["used"] == 20.0 and got["left"] == 95.0
    assert [i["kind"] for i in billing.invoices(db, "ana")] == ["topup", "plan"]
    with pytest.raises(billing.BillingError):
        billing.buy_plan(db, "ana", "studio", "29")                          # already on it
    with pytest.raises(billing.BillingError):
        billing.buy_topup(db, "ana", 7, "29")
    with pytest.raises(billing.BillingError):
        billing.set_details(db, "ana", country="US", gstin="27ABCDE1234F1Z5")
    with pytest.raises(billing.BillingError):
        billing.set_details(db, "ana", country="IN", gstin="27ABCDE")


def test_a_declined_payment_changes_nothing(db):
    billing.account(db, "bo")
    STRIPE.fail_next = True
    with pytest.raises(billing.BillingError, match="did not go through"):
        billing.buy_topup(db, "bo", 25, "29")
    assert billing.invoices(db, "bo") == []
    assert billing.credits(db, "bo", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS


def test_the_invoice_page_says_test_mode_and_shows_the_split(db):
    billing.set_details(db, "cy", country="IN", state_code="29")
    inv = billing.buy_topup(db, "cy", 10, "29")
    page = billing.invoice_html(inv, {"name": "Voltage", "gstin": "", "state": "29"})
    assert "Test mode. No money moved" in page and "CGST 9%" in page and "SGST 9%" in page and "Karnataka" in page
    assert "—" not in page


def test_migration_0028_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    mine = {"billing_accounts", "credit_grants", "invoices"}
    assert mine <= tabs()
    migrate.down(conn, max(migrate.applied(conn)) - 27)   # back to 0027
    assert not (mine & tabs()) and "feedback" in tabs()
    migrate.up(conn)
    assert mine <= tabs()


def test_plan_credits_lapse_at_the_months_end_and_top_ups_after_twelve_months():
    """Decision 0: spend comes out of the soonest-to-lapse grant first; what a
    plan month leaves unused lapses when the month ends, a top-up after 12 months."""
    grants = [
        {"kind": "trial", "credits": 5.0, "period": None, "at": "2026-09-01T00:00:00.000Z"},
        {"kind": "plan", "credits": 50.0, "period": "2026-09", "at": "2026-09-01T00:00:00.000Z"},
        {"kind": "topup", "credits": 10.0, "period": None, "at": "2026-09-10T00:00:00.000Z"},
        {"kind": "plan", "credits": 50.0, "period": "2026-10", "at": "2026-10-01T00:00:00.000Z"},
    ]
    # $30 spent in September, $20 in October.
    spend = [("2026-09-15T00:00:00.000Z", 30.0), ("2026-10-15T00:00:00.000Z", 20.0)]
    since = lambda at: sum(usd for when, usd in spend if when >= at)  # noqa: E731
    got = billing.balance(grants, since, "2026-09-01T00:00:00.000Z", "2026-10-20T00:00:00.000Z")
    # September's plan paid the $30 and lapsed with 20 left; October's plan paid $20; trial and top-up untouched.
    assert got == {"used": 50.0, "left": 45.0, "lapsed": 20.0}
    assert [g["left"] for g in grants] == [5.0, 0.0, 10.0, 30.0]
    assert grants[2]["expires_at"] == "2027-09-10T00:00:00.000Z" and grants[0]["expires_at"] is None
    assert billing.expires_at("plan", "2026-12", "x") == "2027-01-01T00:00:00.000Z"
    later = billing.balance([dict(g) for g in grants], since, "2026-09-01T00:00:00.000Z", "2027-10-01T00:00:00.000Z")
    assert later["left"] == 5.0                                           # only the trial outlives a year


def test_spend_past_the_credits_is_owed_from_the_next_grant():
    grants = [{"kind": "trial", "credits": 5.0, "period": None, "at": "2026-09-01T00:00:00.000Z"},
              {"kind": "topup", "credits": 10.0, "period": None, "at": "2026-09-20T00:00:00.000Z"}]
    since = lambda at: 8.0 if at <= "2026-09-05T00:00:00.000Z" else 0.0  # noqa: E731
    got = billing.balance(grants, since, "2026-09-01T00:00:00.000Z", "2026-09-30T00:00:00.000Z")
    assert got["left"] == 7.0 and got["lapsed"] == 0.0
