"""A small in-memory rate limit (G7, G8): at most `limit` hits per `window`
seconds for one key (an owner, an address). Enough for one server; a fleet
would put this in shared storage."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimit:
    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Count one hit for `key`; False when it is over the limit (the hit is not counted)."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:            # forget idle keys
                for k in [k for k, d in self._hits.items() if not d or d[-1] <= now - self.window]:
                    self._hits.pop(k, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# ── Launch item 2: per-user limits on the costly and abusable routes ─────────
# Each bucket: (methods, path pattern, hits, window seconds). Keyed by the
# signed-in person, or by the caller's address where the caller is a link
# holder (a review comment). Sign-in is keyed by the account being tried
# (its address, or its emailed token) plus the caller's address, so an office
# behind one address can all sign up at once while one account is still hard
# to guess; a looser ceiling per address stops one address spraying many
# accounts (run 4 item 4a). Any bucket can be changed with
# AVE_RATE_<NAME>="hits/seconds" (e.g. AVE_RATE_TURNS=60/600).

import os
import re

_ID = r"[^/]+"
_AUTH = r"^/auth/(login|callback|email|email/callback|password.*|signup|verify.*|reset.*|change-email.*)$"
BUCKETS: dict[str, tuple[tuple[str, ...], str, int, float, str]] = {
    # name: (methods, pattern, hits, window, key: "user" | "ip" | "account")
    "turns": (("POST",), rf"^/(videos|projects)/{_ID}/turns(/allow-more)?$|^/projects/{_ID}/batches(/{_ID}/go)?$|^/projects/{_ID}/brief-update$",
              30, 600.0, "user"),
    "synth": (("POST",), rf"^/voices/(design|mine(/from-speaker|/from-preview)?)$|^/videos/{_ID}/plans/{_ID}/items/{_ID}/ease$"
                         rf"|^/videos/{_ID}/(variants|languages|sync)$|^/videos/{_ID}/liveness/{_ID}$", 20, 600.0, "user"),
    "uploads": (("POST",), rf"^/videos$|^/projects/{_ID}/files$|^/projects/{_ID}/rules/{_ID}/audio$", 30, 3600.0, "user"),
    "imports": (("POST",), r"^/imports$", 10, 3600.0, "user"),
    "auth": (("GET", "POST"), _AUTH, 20, 600.0, "account"),
    "auth_ip": (("GET", "POST"), _AUTH, 100, 600.0, "ip"),
    "comments": (("POST",), rf"^/share/{_ID}/(comments|approve|changes)$|^/videos/{_ID}/comments(/{_ID}/replies)?$", 30, 600.0, "user"),
    "abuse": (("POST",), r"^/abuse-reports$", 5, 3600.0, "ip"),
    "waitlist": (("POST",), r"^/waitlist$", 5, 3600.0, "ip"),            # launch item 8: Request access
}


class Limits:
    """The buckets above, each its own RateLimit."""

    def __init__(self, buckets: dict = BUCKETS, clock: Callable[[], float] = time.monotonic) -> None:
        self.rules = []
        for name, (methods, pattern, hits, window, key) in buckets.items():
            override = os.environ.get(f"AVE_RATE_{name.upper()}", "")
            if "/" in override:
                hits, window = int(override.split("/")[0]), float(override.split("/")[1])
            self.rules.append((name, frozenset(methods), re.compile(pattern), key, RateLimit(hits, window, clock)))

    def check(self, method: str, path: str, user: str | None, ip: str, account: str | None = None) -> str | None:
        """The bucket's name when this request is over its limit (not counted), else None.
        `account` is the account a sign-in request names; without one only the address ceiling applies."""
        path = path[4:] if path.startswith("/api/") else path
        for name, methods, pattern, key, limit in self.rules:
            if method in methods and pattern.match(path):
                if key == "account" and not account:
                    continue
                who = (user or ip) if key == "user" else f"{account.strip().lower()}|{ip}" if key == "account" else ip
                if not limit.allow(f"{name}:{who}"):
                    return name
        return None

    def keys_by_account(self, method: str, path: str) -> bool:
        """Whether this request needs `account` (so the caller reads the body only then)."""
        path = path[4:] if path.startswith("/api/") else path
        return any(key == "account" and method in methods and pattern.match(path)
                   for _name, methods, pattern, key, _limit in self.rules)

    def window(self, name: str) -> float:
        return next(r[4].window for r in self.rules if r[0] == name)

    def reset(self) -> None:
        for rule in self.rules:
            rule[4].reset()


WORDS = {
    "turns": "That is a lot of requests to Voltage in a short time.",
    "synth": "That is a lot of voicing in a short time.",
    "uploads": "That is a lot of uploads in a short time.",
    "imports": "That is a lot of imports in a short time.",
    "auth": "Too many sign-in attempts from here.",
    "auth_ip": "Too many sign-in attempts from here.",
    "comments": "That is a lot of comments in a short time.",
    "abuse": "Thanks. We have your reports; please wait before sending more.",
    "waitlist": "That is a lot of requests from here.",
}


def refusal(name: str, window: float) -> str:
    minutes = max(1, round(window / 60))
    return f"{WORDS[name]} Try again in {minutes} {'minute' if minutes == 1 else 'minutes'}."
