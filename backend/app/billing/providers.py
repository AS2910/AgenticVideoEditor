"""G3: payment providers behind one interface, both fake.

    provider_for(country) -> BillingProvider     Razorpay for India, Stripe elsewhere
    provider.checkout(owner, description, amount, currency) -> Checkout

No account, key or network: a fake checkout is paid at once in test mode
and says so (`test_mode`), so the Billing page can label it. A real
provider replaces `checkout` with a hosted payment page and a webhook that
confirms it (SETUP_NEEDED.md).
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Checkout:
    checkout_id: str
    provider: str
    status: str            # paid | failed
    amount: float
    currency: str
    test_mode: bool


class BillingProvider(Protocol):
    name: str
    label: str
    test_mode: bool

    def checkout(self, owner: str, description: str, amount: float, currency: str) -> Checkout: ...


class FakeProvider:
    """A provider that takes no money: every checkout is paid, in test mode."""

    test_mode = True

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


STRIPE = FakeProvider("stripe", "Stripe (test mode)", "cs")
RAZORPAY = FakeProvider("razorpay", "Razorpay (test mode)", "order")


def provider_for(country: str | None) -> FakeProvider:
    """Razorpay bills India (INR, UPI and cards); Stripe bills everyone else (USD)."""
    return RAZORPAY if (country or "").upper() == "IN" else STRIPE
