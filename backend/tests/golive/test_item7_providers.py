"""Item 7: real providers, code only, off without keys. Every HTTP call is
mocked (httpx.MockTransport). Stripe: a Checkout Session per purchase (form,
Bearer, Idempotency-Key, cents), credits only after a signed webhook, the
signature good/bad/expired, the same event twice grants once, refunds take
the credits back. Razorpay: an Order (basic auth, paise), the signed payment
and the `payment.captured` webhook grant once between them, refunds. Resend:
the request, retries under one Idempotency-Key, no retry on a refusal, the
outbox without a key. Sentry: the envelope, its auth header, nothing secret
in it, a bad DSN or a dead endpoint never raises. Without keys the fakes
answer exactly as before."""
import dataclasses
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app import billing, errors_report
from app.api import main
from app.billing import providers, webhooks
from app.billing.providers import (
    RAZORPAY,
    STRIPE,
    RazorpayProvider,
    StripeProvider,
    WebhookRejected,
    provider_for,
    verify_razorpay_webhook,
    verify_stripe_signature,
)
from app.notify import email
from app.store.db import Database

WHSEC = "whsec_test_secret"
RZP_SECRET = "rzp_secret"
RZP_HOOK = "rzp_hook_secret"


class Recorder:
    """A mocked transport that answers from a list and keeps every request."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def ok(body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def stripe_sig(payload: bytes, secret: str = WHSEC, at: int | None = None) -> str:
    at = int(time.time()) if at is None else at
    return f"t={at},v1={hmac.new(secret.encode(), f'{at}.'.encode() + payload, hashlib.sha256).hexdigest()}"


def rzp_sig(payload: bytes, secret: str = RZP_HOOK) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "t.db")


# ── signatures ───────────────────────────────────────────────────────────────

def test_stripe_signature_good_bad_expired_and_malformed():
    body = b'{"id": "evt_1"}'
    assert verify_stripe_signature(body, stripe_sig(body), WHSEC)["id"] == "evt_1"
    assert verify_stripe_signature(body, stripe_sig(body) + ",v1=other,v0=old", WHSEC)["id"] == "evt_1"   # any v1 may match
    for header in (None, "", "v1=abc", "t=abc,v1=abc", stripe_sig(body, "whsec_other"), stripe_sig(b'{"id": "evt_2"}')):
        with pytest.raises(WebhookRejected):
            verify_stripe_signature(body, header, WHSEC)
    old = int(time.time()) - 301
    with pytest.raises(WebhookRejected, match="too old"):
        verify_stripe_signature(body, stripe_sig(body, at=old), WHSEC)
    assert verify_stripe_signature(body, stripe_sig(body, at=old), WHSEC, now=old + 299)["id"] == "evt_1"


def test_razorpay_signatures():
    body = b'{"event": "payment.captured"}'
    assert verify_razorpay_webhook(body, rzp_sig(body), RZP_HOOK)["event"] == "payment.captured"
    for sig in (None, "", rzp_sig(body, "other"), rzp_sig(b"{}")):
        with pytest.raises(WebhookRejected):
            verify_razorpay_webhook(body, sig, RZP_HOOK)
    rzp = RazorpayProvider("rzp_test_k", RZP_SECRET, RZP_HOOK, client=Recorder(ok({})).client())
    good = hmac.new(RZP_SECRET.encode(), b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert rzp.verify_payment("order_1", "pay_1", good)
    assert not rzp.verify_payment("order_1", "pay_2", good) and not rzp.verify_payment("order_1", "pay_1", None)


# ── off without keys ─────────────────────────────────────────────────────────

def test_without_keys_the_fakes_answer():
    bare = main.settings
    assert bare.stripe_secret_key is None and bare.razorpay_key_id is None
    assert provider_for("US", bare) is STRIPE and provider_for("IN", bare) is RAZORPAY
    half = dataclasses.replace(bare, stripe_secret_key="sk_test_x")            # no webhook secret: still fake
    assert provider_for("US", half) is STRIPE
    real = dataclasses.replace(bare, stripe_secret_key="sk_test_x", stripe_webhook_secret=WHSEC,
                               razorpay_key_id="rzp_test_k", razorpay_key_secret=RZP_SECRET)
    assert isinstance(provider_for("US", real), StripeProvider) and isinstance(provider_for("IN", real), RazorpayProvider)
    assert provider_for("US", real).label == "Stripe (test mode)"
    assert errors_report.reporter_for(None).name == "log"


# ── Stripe ───────────────────────────────────────────────────────────────────

def test_stripe_checkout_request_and_nothing_granted_until_the_webhook(db):
    rec = Recorder(ok({"id": "cs_123", "url": "https://checkout.stripe.com/c/cs_123"}))
    stripe = StripeProvider("sk_test_abc", WHSEC, "https://app.example", client=rec.client())
    made = billing.buy_topup(db, "ana", 10, "29", provider=stripe)
    assert made["pending"] and made["checkout"]["url"].endswith("cs_123") and made["checkout"]["total"] == 12.0
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == "https://api.stripe.com/v1/checkout/sessions"
    assert req.headers["Authorization"] == "Bearer sk_test_abc" and req.headers["Idempotency-Key"].startswith("checkout-")
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert form["mode"] == "payment" and form["line_items[0][price_data][unit_amount]"] == "1200"
    assert form["line_items[0][price_data][currency]"] == "usd" and form["metadata[owner]"] == "ana"
    assert form["metadata[kind]"] == "topup" and form["success_url"] == "https://app.example/?checkout=done#billing"
    assert billing.invoices(db, "ana") == []
    assert billing.credits(db, "ana", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS


def _session_event(event_id: str, session: str = "cs_123", amount: int = 1200, paid: str = "paid") -> dict:
    return {"id": event_id, "type": "checkout.session.completed", "livemode": False,
            "data": {"object": {"id": session, "payment_status": paid, "payment_intent": "pi_9", "amount_total": amount,
                                "currency": "usd"}}}


def test_stripe_webhook_grants_once_and_a_refund_takes_it_back(db):
    rec = Recorder(ok({"id": "cs_123", "url": "u"}), ok({"id": "re_1"}))
    stripe = StripeProvider("sk_test_abc", WHSEC, "https://app.example", client=rec.client())
    billing.buy_topup(db, "ana", 10, "29", provider=stripe)
    unpaid = webhooks.handle_stripe(db, stripe, _session_event("evt_0", paid="unpaid"), "29")
    assert unpaid["handled"] is False
    first = webhooks.handle_stripe(db, stripe, _session_event("evt_1"), "29")
    assert first["handled"] and first["invoice"].startswith("VLT-")
    assert webhooks.handle_stripe(db, stripe, _session_event("evt_1"), "29") == {"ok": True, "duplicate": True}
    assert webhooks.handle_stripe(db, stripe, _session_event("evt_2"), "29")["handled"] is False   # another event, same payment
    assert webhooks.handle_stripe(db, stripe, _session_event("evt_3", session="cs_unknown"), "29")["handled"] is False
    assert billing.credits(db, "ana", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS + 10
    [inv] = billing.invoices(db, "ana")
    assert (inv["provider"], inv["checkout_id"], inv["total"], inv["test_mode"]) == ("stripe", "pi_9", 12.0, True)
    done = billing.refund(db, "ana", inv["id"], provider=stripe)
    assert done["credits_taken_back"] == 10 and done["refund_id"] == "re_1"
    req = rec.requests[-1]
    assert str(req.url) == "https://api.stripe.com/v1/refunds" and req.headers["Authorization"] == "Bearer sk_test_abc"
    assert req.headers["Idempotency-Key"] == f"refund-{inv['number']}"
    assert {k: v[0] for k, v in parse_qs(req.content.decode()).items()} == {"payment_intent": "pi_9", "amount": "1200"}
    assert billing.credits(db, "ana", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS
    with pytest.raises(billing.BillingError, match="refunded already"):
        billing.refund(db, "ana", inv["id"], provider=stripe)


def test_a_paid_amount_that_does_not_match_grants_nothing(db):
    stripe = StripeProvider("sk_test_abc", WHSEC, "https://app.example", client=Recorder(ok({"id": "cs_123"})).client())
    billing.buy_topup(db, "ana", 10, "29", provider=stripe)
    assert webhooks.handle_stripe(db, stripe, _session_event("evt_1", amount=1), "29")["handled"] is False
    assert billing.invoices(db, "ana") == []


def test_a_plan_refund_ends_the_plan(db):
    rec = Recorder(ok({"id": "cs_p", "url": "u"}), ok({"id": "re_2"}))
    stripe = StripeProvider("sk_live_abc", WHSEC, "https://app.example", client=rec.client())
    assert stripe.label == "Stripe" and not stripe.test_mode
    billing.buy_plan(db, "bo", "starter", "29", provider=stripe)
    event = _session_event("evt_p", session="cs_p", amount=1900)
    event["livemode"] = True
    assert webhooks.handle_stripe(db, stripe, event, "29")["handled"]
    assert billing.account(db, "bo")["plan"] == "starter"
    [inv] = billing.invoices(db, "bo")
    assert inv["test_mode"] is False
    billing.refund(db, "bo", inv["id"], provider=stripe)
    assert billing.account(db, "bo")["plan"] is None
    assert billing.credits(db, "bo", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS


def test_a_failed_refund_changes_nothing_and_can_be_tried_again(db):
    rec = Recorder(ok({"id": "cs_123"}), ok({"error": {"message": "nope"}}, 402), ok({"id": "re_3"}))
    stripe = StripeProvider("sk_test_abc", WHSEC, "https://app.example", client=rec.client())
    billing.buy_topup(db, "ana", 10, "29", provider=stripe)
    webhooks.handle_stripe(db, stripe, _session_event("evt_1"), "29")
    [inv] = billing.invoices(db, "ana")
    with pytest.raises(billing.BillingError, match="did not go through"):
        billing.refund(db, "ana", inv["id"], provider=stripe)
    assert billing.credits(db, "ana", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS + 10
    assert billing.refund(db, "ana", inv["id"], provider=stripe)["refund_id"] == "re_3"


def test_a_stripe_outage_is_a_sentence(db):
    stripe = StripeProvider("sk_test_abc", WHSEC, "https://app.example",
                            client=Recorder(httpx.ConnectTimeout("slow")).client())
    with pytest.raises(billing.BillingError, match="could not open the payment page"):
        billing.buy_topup(db, "ana", 10, "29", provider=stripe)


def test_the_fake_provider_refunds_too(db):
    inv = billing.buy_topup(db, "cy", 25, "29")
    assert billing.refund(db, "cy", inv["id"])["credits_taken_back"] == 25
    assert billing.credits(db, "cy", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS


# ── Razorpay ─────────────────────────────────────────────────────────────────

def test_razorpay_order_request_and_refund(db):
    rec = Recorder(ok({"id": "order_7"}), ok({"id": "rfnd_7"}))
    rzp = RazorpayProvider("rzp_test_k", RZP_SECRET, RZP_HOOK, client=rec.client())
    billing.set_details(db, "dev", country="IN", state_code="29")
    made = billing.buy_topup(db, "dev", 10, "29", provider=rzp)
    client = made["checkout"]["client"]
    assert client["order_id"] == "order_7" and client["key_id"] == "rzp_test_k" and client["currency"] == "INR"
    req = rec.requests[0]
    assert str(req.url) == "https://api.razorpay.com/v1/orders" and req.headers["Idempotency-Key"].startswith("checkout-")
    assert req.headers["Authorization"] == "Basic " + __import__("base64").b64encode(f"rzp_test_k:{RZP_SECRET}".encode()).decode()
    body = json.loads(req.content)
    total = billing.gst.split(10 * billing.TOPUP_MARKUP * billing.INR_PER_USD, "IN", "29", "29").total
    assert body["amount"] == round(total * 100) == client["amount"] and body["notes"]["owner"] == "dev"
    inv = billing.fulfil(db, "razorpay", "order_7", "pay_7", "29", test_mode=True)
    assert inv["checkout_id"] == "pay_7" and billing.fulfil(db, "razorpay", "order_7", "pay_7", "29", test_mode=True) is None
    billing.refund(db, "dev", inv["id"], provider=rzp)
    req = rec.requests[-1]
    assert str(req.url) == "https://api.razorpay.com/v1/payments/pay_7/refund"
    assert json.loads(req.content)["amount"] == round(total * 100) and req.headers["Idempotency-Key"] == f"refund-{inv['number']}"
    assert billing.credits(db, "dev", lambda at: 0.0)["granted"] == billing.TRIAL_CREDITS


# ── through the API ──────────────────────────────────────────────────────────

@pytest.fixture()
def live(monkeypatch):
    """The app with both real providers on (test keys) and every call mocked."""
    main.repo.reset()
    rec = Recorder(ok({"id": "cs_api", "url": "https://checkout.stripe.com/c/cs_api"}))
    monkeypatch.setattr(providers, "http_client", rec.client)
    monkeypatch.setattr(providers, "_real", {})
    monkeypatch.setattr(main, "settings", dataclasses.replace(
        main.settings, stripe_secret_key="sk_test_api", stripe_webhook_secret=WHSEC, razorpay_key_id="rzp_test_api",
        razorpay_key_secret=RZP_SECRET, razorpay_webhook_secret=RZP_HOOK))
    yield rec
    main.repo.reset()
    main.flags.clear("golive.g3", "local")


def test_api_stripe_checkout_then_webhook(live):
    client = TestClient(main.app)
    view = client.get("/billing").json()
    assert view["provider"] == {"name": "stripe", "label": "Stripe (test mode)", "test_mode": True}
    started = client.post("/billing/topup", json={"credits": 10})
    assert started.status_code == 200, started.text
    assert started.json()["checkout"]["url"].endswith("cs_api") and started.json()["credits"]["granted"] == 5.0
    body = json.dumps(_session_event("evt_api", session="cs_api")).encode()
    for headers in ({}, {"Stripe-Signature": "t=1,v1=bad"}, {"Stripe-Signature": stripe_sig(body, at=int(time.time()) - 600)}):
        assert client.post("/billing/webhooks/stripe", content=body, headers=headers).status_code == 400
    good = {"Stripe-Signature": stripe_sig(body), "Content-Type": "application/json"}
    first = client.post("/billing/webhooks/stripe", content=body, headers=good)
    assert first.status_code == 200 and first.json()["handled"]
    assert client.post("/billing/webhooks/stripe", content=body, headers=good).json()["duplicate"]
    assert client.get("/billing").json()["credits"]["granted"] == 15.0


def test_api_razorpay_verify_and_webhook_grant_once(live):
    client = TestClient(main.app)
    client.put("/billing/details", json={"country": "IN", "state_code": "29"})
    live.answers = [ok({"id": "order_api"})]
    started = client.post("/billing/topup", json={"credits": 10}).json()
    assert started["checkout"]["client"]["order_id"] == "order_api"
    bad = client.post("/billing/razorpay/verify", json={"order_id": "order_api", "payment_id": "pay_1", "signature": "x"})
    assert bad.status_code == 400
    assert client.post("/billing/razorpay/verify", json={"order_id": "order_x", "payment_id": "p", "signature": "x"}).status_code == 404
    sig = hmac.new(RZP_SECRET.encode(), b"order_api|pay_1", hashlib.sha256).hexdigest()
    paid = client.post("/billing/razorpay/verify", json={"order_id": "order_api", "payment_id": "pay_1", "signature": sig})
    assert paid.status_code == 200 and paid.json()["invoice"]["checkout_id"] == "pay_1"
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_1", "order_id": "order_api", "amount": started["checkout"]["client"]["amount"], "currency": "INR"}}}}
    body = json.dumps(event).encode()
    assert client.post("/billing/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    assert client.post("/billing/webhooks/razorpay", content=body).status_code == 400
    hook = client.post("/billing/webhooks/razorpay", content=body,
                       headers={"X-Razorpay-Signature": rzp_sig(body), "X-Razorpay-Event-Id": "ev_1"})
    assert hook.status_code == 200 and hook.json()["handled"] is False         # the signed payment granted it already
    again = client.post("/billing/webhooks/razorpay", content=body,
                        headers={"X-Razorpay-Signature": rzp_sig(body), "X-Razorpay-Event-Id": "ev_1"})
    assert again.json()["duplicate"]
    view = client.get("/billing").json()
    assert view["credits"]["granted"] == 15.0 and len(view["invoices"]) == 1


def test_api_admin_refund(live):
    client = TestClient(main.app)
    client.get("/billing")
    live.answers = [ok({"id": "cs_api", "url": "u"})]
    client.post("/billing/topup", json={"credits": 25})
    body = json.dumps(_session_event("evt_r", session="cs_api", amount=3000)).encode()
    assert client.post("/billing/webhooks/stripe", content=body, headers={"Stripe-Signature": stripe_sig(body)}).json()["handled"]
    inv = client.get("/billing").json()["invoices"][0]
    live.answers = [ok({"id": "re_api"})]
    done = client.post("/admin/billing/refund", json={"owner": "local", "invoice_id": inv["id"]})
    assert done.status_code == 200, done.text
    assert done.json()["credits_taken_back"] == 25 and client.get("/billing").json()["credits"]["granted"] == 5.0
    assert client.post("/admin/billing/refund", json={"owner": "local", "invoice_id": inv["id"]}).status_code == 422
    assert client.post("/admin/billing/refund", json={"owner": "local", "invoice_id": 999}).status_code == 404


def test_api_webhooks_are_not_there_without_keys():
    client = TestClient(main.app)
    assert client.post("/billing/webhooks/stripe", content=b"{}").status_code == 404
    assert client.post("/billing/webhooks/razorpay", content=b"{}").status_code == 404


# ── Resend ───────────────────────────────────────────────────────────────────

def _mail(**kw) -> email.Email:
    return email.Email(to="a@b.co", subject="Hi", body="Body", kind="version_ready", owner="ana", **kw)


def test_resend_sends_the_email_with_its_key(db):
    rec = Recorder(ok({"id": "em_1"}))
    sender = email.ResendEmail(db, "re_key", "Voltage <hi@voltage.example>", client=rec.client(), sleep=lambda s: None)
    sender.send(_mail())
    req = rec.requests[0]
    assert str(req.url) == "https://api.resend.com/emails" and req.headers["Authorization"] == "Bearer re_key"
    assert req.headers["Idempotency-Key"].startswith("version_ready-")
    assert json.loads(req.content) == {"from": "Voltage <hi@voltage.example>", "to": ["a@b.co"], "subject": "Hi", "text": "Body"}
    assert [r["provider"] for r in email.outbox(db)] == ["resend"]


def test_resend_retries_transient_failures_under_one_key(db):
    slept = []
    rec = Recorder(httpx.Response(503), httpx.ReadTimeout("slow"), ok({"id": "em_2"}))
    email.ResendEmail(db, "k", "f@x.co", client=rec.client(), sleep=slept.append).send(_mail())
    assert len(rec.requests) == 3 and len({r.headers["Idempotency-Key"] for r in rec.requests}) == 1
    assert slept == [0.5, 1.0] and email.outbox(db)[-1]["provider"] == "resend"
    gone = Recorder(httpx.Response(500))
    email.ResendEmail(db, "k", "f@x.co", client=gone.client(), sleep=lambda s: None).send(_mail())
    assert len(gone.requests) == 3 and email.outbox(db)[-1]["provider"] == "resend (failed)"
    refused = Recorder(httpx.Response(422, json={"message": "bad from"}))
    email.ResendEmail(db, "k", "f@x.co", client=refused.client(), sleep=lambda s: None).send(_mail())
    assert len(refused.requests) == 1


def test_resend_only_with_a_key_and_a_sender(db, monkeypatch):
    assert isinstance(email.sender_for("resend", db), email.OutboxEmail) and email.sender_for("resend", db).name == "outbox"
    assert email.sender_for("resend", db, api_key="k").name == "outbox"                       # no from address
    assert isinstance(email.sender_for("resend", db, api_key="k", from_addr="f@x.co"), email.ResendEmail)
    monkeypatch.setenv("RESEND_API_KEY", "k2")
    monkeypatch.setenv("AVE_EMAIL_FROM", "f@x.co")
    assert email.sender_for("Resend", db).api_key == "k2"
    assert email.sender_for("outbox", db).name == "outbox"


# ── Sentry ───────────────────────────────────────────────────────────────────

def test_sentry_posts_a_scrubbed_envelope(db):
    rec = Recorder(ok({"id": "x"}))
    sentry = errors_report.SentryReporter("https://pubkey@o9.ingest.sentry.io/42", db, client=rec.client(),
                                          submit=lambda send: send())
    try:
        raise ValueError("charge failed for sk_live_abcdefgh12345 with Bearer tok123")
    except ValueError as exc:
        sentry.capture_exception(exc, {"where": "POST /billing/plan", "owner": "ana", "cookie": "ave_session=1",
                                       "headers": {"Authorization": "Bearer x", "accept": "json"}, "body": "{...}"})
    req = rec.requests[0]
    assert str(req.url) == "https://o9.ingest.sentry.io/api/42/envelope/"
    assert req.headers["X-Sentry-Auth"].startswith("Sentry sentry_version=7, sentry_key=pubkey")
    head, item, event = (json.loads(line) for line in req.content.decode().strip().split("\n"))
    assert head["event_id"] == event["event_id"] and item["type"] == "event"
    text = json.dumps(event)
    assert "sk_live" not in text and "tok123" not in text and "ave_session" not in text and "{...}" not in text
    assert event["tags"] == {"where": "POST /billing/plan"} and event["user"] == {"id": "ana"}
    assert event["extra"]["headers"] == {"Authorization": "[removed]", "accept": "json"}
    assert event["exception"]["values"][0]["type"] == "ValueError"
    sentry.capture_message("hello", level="warning", context={"source": "client"})
    msg = json.loads(rec.requests[1].content.decode().strip().split("\n")[2])
    assert msg["message"] == {"formatted": "hello"} and msg["level"] == "warning"
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM error_reports").fetchone()[0] == 2        # still kept locally


def test_sentry_never_raises(db):
    dead = errors_report.SentryReporter("https://k@sentry.example/1", db, client=Recorder(httpx.ConnectError("down")).client(),
                                        submit=lambda send: send())
    dead.capture_message("still fine")
    bad = errors_report.SentryReporter("not a dsn", db, submit=lambda send: pytest.fail("nothing to send"))
    assert "bad DSN" in bad.name
    bad.capture_message("local only")
    assert errors_report.Dsn.parse("https://k@host:9000/sub/7").envelope_url == "https://host:9000/sub/api/7/envelope/"
