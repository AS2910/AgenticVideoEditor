"""G3: payment providers behind one interface. Fake (test mode) unless keys exist.

    provider_for(country, settings=None) -> BillingProvider   Razorpay for India, Stripe elsewhere
    provider_named(name, settings=None) -> BillingProvider    the one that took a payment (refunds)
    provider.checkout(owner, description, amount, currency) -> Checkout     fake: paid at once
    provider.start(owner, description, amount, currency, metadata, idempotency_key) -> Checkout
                                                              real: a hosted page or an order, pending
    provider.refund(payment_ref, amount, currency, idempotency_key) -> refund id

Without keys (and always when `settings` is None) the fake providers answer:
no account, key or network, every checkout paid at once in test mode, and it
says so (`test_mode`). Item 7: with `AVE_STRIPE_SECRET_KEY` and
`AVE_STRIPE_WEBHOOK_SECRET` Stripe is real; with `AVE_RAZORPAY_KEY_ID` and
`AVE_RAZORPAY_KEY_SECRET` Razorpay is. A real provider never grants
anything itself: it opens a payment, and credits come only from a verified
webhook (or, for Razorpay, the signed payment the browser hands back).
Both talk REST over httpx, no SDK; every POST carries an Idempotency-Key.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

TIMEOUT = 10.0
WEBHOOK_TOLERANCE = 300          # seconds a Stripe signature stays good


@dataclass(frozen=True)
class Checkout:
    checkout_id: str
    provider: str
    status: str            # paid | failed | pending (a real provider: paid once the webhook says so)
    amount: float
    currency: str
    test_mode: bool
    url: str = ""          # Stripe: the hosted Checkout page to send the buyer to
    client: dict | None = None   # Razorpay: what checkout.js needs (key id, order id, amount in paise)


class ProviderError(RuntimeError):
    """The provider refused or could not be reached; nothing was charged or refunded."""


class WebhookRejected(ValueError):
    """A webhook whose signature is missing, wrong or too old."""


class BillingProvider(Protocol):
    name: str
    label: str
    test_mode: bool
    hosted: bool

    def checkout(self, owner: str, description: str, amount: float, currency: str) -> Checkout: ...

    def refund(self, payment_ref: str, amount: float, currency: str, idempotency_key: str) -> str: ...


class FakeProvider:
    """A provider that takes no money: every checkout is paid, in test mode."""

    test_mode = True
    hosted = False

    def __init__(self, name: str, label: str, prefix: str) -> None:
        self.name, self.label, self.prefix = name, label, prefix
        self._n = itertools.count(1)
        self._lock = threading.Lock()
        self.fail_next = False          # tests: the next checkout is declined

    def checkout(self, owner: str, description: str, amount: float, currency: str) -> Checkout:
        with self._lock:
            n = next(self._n)
            failed, self.fail_next = self.fail_next, False
        return Checkout(f"{self.prefix}_test_{n:05d}", self.name, "failed" if failed else "paid", round(amount, 2), currency, True)

    def refund(self, payment_ref: str, amount: float, currency: str, idempotency_key: str) -> str:
        with self._lock:
            return f"rfnd_test_{next(self._n):05d}"


def minor(amount: float) -> int:
    """Cents or paise: what both APIs count in."""
    return round(float(amount) * 100)


def _strs(metadata: dict) -> dict[str, str]:
    return {str(k): str(v) for k, v in metadata.items() if v is not None}


def _send(client: httpx.Client, url: str, idempotency_key: str, **kwargs) -> dict:
    """One POST; a refusal or a network failure is a ProviderError with the provider's own words for the log."""
    headers = {**kwargs.pop("headers", {}), "Idempotency-Key": idempotency_key}
    try:
        r = client.post(url, headers=headers, timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        raise ProviderError(f"could not reach {url}: {type(exc).__name__}") from None
    if r.status_code >= 400:
        try:
            said = r.json().get("error", {})
            said = said.get("message") or said.get("description") or r.text[:200]
        except ValueError:
            said = r.text[:200]
        raise ProviderError(f"{url} answered {r.status_code}: {said}")
    return r.json()


def verify_stripe_signature(payload: bytes, header: str | None, secret: str, now: float | None = None,
                            tolerance: int = WEBHOOK_TOLERANCE) -> dict:
    """The event, when `Stripe-Signature` (t=..., v1=...) is an HMAC-SHA256 of
    "{t}.{payload}" with the webhook secret and t is within five minutes."""
    if not header or not secret:
        raise WebhookRejected("no signature")
    stamp, sigs = None, []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            stamp = value
        elif key == "v1":
            sigs.append(value)
    if not stamp or not stamp.isdigit() or not sigs:
        raise WebhookRejected("malformed signature")
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise WebhookRejected("signature does not match")
    if abs((time.time() if now is None else now) - int(stamp)) > tolerance:
        raise WebhookRejected("signature too old")
    try:
        return json.loads(payload)
    except ValueError:
        raise WebhookRejected("not JSON") from None


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_razorpay_webhook(payload: bytes, signature: str | None, secret: str) -> dict:
    """The event, when `X-Razorpay-Signature` is an HMAC-SHA256 of the raw body with the webhook secret."""
    if not signature or not secret or not hmac.compare_digest(_hmac_hex(secret, payload), signature):
        raise WebhookRejected("signature does not match")
    try:
        return json.loads(payload)
    except ValueError:
        raise WebhookRejected("not JSON") from None


class StripeProvider:
    """Stripe (USD): a hosted Checkout Session per purchase; `checkout.session.completed` pays it."""

    name = "stripe"
    hosted = True
    API = "https://api.stripe.com"

    def __init__(self, secret_key: str, webhook_secret: str, public_url: str, client: httpx.Client | None = None) -> None:
        self.secret_key, self.webhook_secret = secret_key, webhook_secret
        self.public_url = public_url.rstrip("/")
        self.test_mode = secret_key.startswith(("sk_test_", "rk_test_"))
        self.label = "Stripe (test mode)" if self.test_mode else "Stripe"
        self.client = client or httpx.Client()

    def _post(self, path: str, form: dict, idempotency_key: str) -> dict:
        return _send(self.client, self.API + path, idempotency_key, data=form,
                     headers={"Authorization": f"Bearer {self.secret_key}"})

    def checkout(self, owner: str, description: str, amount: float, currency: str) -> Checkout:
        raise ProviderError("Stripe takes payment on its hosted page; use start()")

    def start(self, owner: str, description: str, amount: float, currency: str, metadata: dict,
              idempotency_key: str) -> Checkout:
        form = {
            "mode": "payment",
            "success_url": f"{self.public_url}/?checkout=done#billing",
            "cancel_url": f"{self.public_url}/?checkout=cancelled#billing",
            "client_reference_id": str(metadata.get("purchase", "")),
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(minor(amount)),
            "line_items[0][price_data][product_data][name]": description,
        }
        for key, value in _strs(metadata).items():
            form[f"metadata[{key}]"] = value
        made = self._post("/v1/checkout/sessions", form, idempotency_key)
        return Checkout(made["id"], self.name, "pending", round(amount, 2), currency, self.test_mode, url=made.get("url") or "")

    def refund(self, payment_ref: str, amount: float, currency: str, idempotency_key: str) -> str:
        made = self._post("/v1/refunds", {"payment_intent": payment_ref, "amount": str(minor(amount))}, idempotency_key)
        return made["id"]

    def verify_webhook(self, payload: bytes, header: str | None, now: float | None = None) -> dict:
        return verify_stripe_signature(payload, header, self.webhook_secret, now)


class RazorpayProvider:
    """Razorpay (INR): an Order per purchase, paid in checkout.js; the signed
    payment or the `payment.captured` webhook pays it."""

    name = "razorpay"
    hosted = True
    API = "https://api.razorpay.com"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str = "", client: httpx.Client | None = None) -> None:
        self.key_id, self.key_secret, self.webhook_secret = key_id, key_secret, webhook_secret
        self.test_mode = key_id.startswith("rzp_test_")
        self.label = "Razorpay (test mode)" if self.test_mode else "Razorpay"
        self.client = client or httpx.Client()

    def _post(self, path: str, body: dict, idempotency_key: str) -> dict:
        return _send(self.client, self.API + path, idempotency_key, json=body, auth=(self.key_id, self.key_secret))

    def checkout(self, owner: str, description: str, amount: float, currency: str) -> Checkout:
        raise ProviderError("Razorpay takes payment in checkout.js; use start()")

    def start(self, owner: str, description: str, amount: float, currency: str, metadata: dict,
              idempotency_key: str) -> Checkout:
        body = {"amount": minor(amount), "currency": currency.upper(), "receipt": idempotency_key[:40],
                "notes": _strs(metadata)}
        made = self._post("/v1/orders", body, idempotency_key)
        client = {"key_id": self.key_id, "order_id": made["id"], "amount": minor(amount), "currency": currency.upper(),
                  "description": description}
        return Checkout(made["id"], self.name, "pending", round(amount, 2), currency, self.test_mode, client=client)

    def refund(self, payment_ref: str, amount: float, currency: str, idempotency_key: str) -> str:
        made = self._post(f"/v1/payments/{payment_ref}/refund", {"amount": minor(amount), "receipt": idempotency_key[:40]},
                          idempotency_key)
        return made["id"]

    def verify_payment(self, order_id: str, payment_id: str, signature: str | None) -> bool:
        """checkout.js hands back a signature: HMAC-SHA256 of "order_id|payment_id" with the key secret."""
        if not signature:
            return False
        return hmac.compare_digest(_hmac_hex(self.key_secret, f"{order_id}|{payment_id}".encode()), signature)

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        return verify_razorpay_webhook(payload, signature, self.webhook_secret)


STRIPE = FakeProvider("stripe", "Stripe (test mode)", "cs")
RAZORPAY = FakeProvider("razorpay", "Razorpay (test mode)", "order")

# How the real providers get their HTTP client (tests swap in a mocked transport).
http_client = httpx.Client
_real: dict[tuple, object] = {}
_real_lock = threading.Lock()


def real_stripe(settings) -> StripeProvider | None:
    """The real Stripe provider, only when both its keys are set."""
    key, hook = getattr(settings, "stripe_secret_key", None), getattr(settings, "stripe_webhook_secret", None)
    if not (key and hook):
        return None
    cache = ("stripe", key, hook, settings.public_url)
    with _real_lock:
        if cache not in _real:
            _real[cache] = StripeProvider(key, hook, settings.public_url, http_client())
        return _real[cache]


def real_razorpay(settings) -> RazorpayProvider | None:
    """The real Razorpay provider, only when its key id and secret are set (the webhook secret is optional)."""
    key_id, secret = getattr(settings, "razorpay_key_id", None), getattr(settings, "razorpay_key_secret", None)
    if not (key_id and secret):
        return None
    hook = getattr(settings, "razorpay_webhook_secret", None) or ""
    cache = ("razorpay", key_id, secret, hook)
    with _real_lock:
        if cache not in _real:
            _real[cache] = RazorpayProvider(key_id, secret, hook, http_client())
        return _real[cache]


def provider_named(name: str, settings=None):
    """The provider called `name`: the real one when its keys are set, else the fake."""
    if name == "razorpay":
        return (real_razorpay(settings) if settings is not None else None) or RAZORPAY
    return (real_stripe(settings) if settings is not None else None) or STRIPE


def provider_for(country: str | None, settings=None):
    """Razorpay bills India (INR, UPI and cards); Stripe bills everyone else (USD)."""
    return provider_named("razorpay" if (country or "").upper() == "IN" else "stripe", settings)
