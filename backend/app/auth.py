"""Sign-in (Phase 9c): OpenID Connect with Google, a signed session cookie,
and nothing else.

The flow is the authorization-code flow with PKCE. The user's identity comes
from Google's UserInfo endpoint over TLS, fetched with the access token the
code exchange returned — so no JWT has to be verified here and no crypto
library is needed. The session is a cookie this server signs with HMAC-SHA256
(`AVE_SESSION_SECRET`); its payload is the subject, email, name, picture and
when it was issued. `AVE_AUTH=off` (the default) keeps everything open under
the single local owner, as before, for development and for a private machine.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

SESSION_COOKIE = "ave_session"
LOGIN_COOKIE = "ave_login"          # state + PKCE verifier, for the minutes a login takes
SESSION_SECONDS = 30 * 24 * 3600
LOGIN_SECONDS = 10 * 60
# State-changing requests must carry this header: a cross-site form cannot.
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "voltage"

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


class AuthError(Exception):
    """A login that cannot complete, in words for the user."""


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None

    @property
    def owner(self) -> str:
        return f"google:{self.sub}"


# ── signed tokens ─────────────────────────────────────────────────────────────

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: str, *, now: float | None = None) -> str:
    """A tamper-evident token: base64(json) . base64(hmac)."""
    body = dict(payload, iat=int(now if now is not None else time.time()))
    raw = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
    return f"{raw}.{_b64(mac)}"


def verify(token: str | None, secret: str, *, max_age: int, now: float | None = None) -> dict | None:
    """The payload, or None when the token is missing, altered or too old."""
    if not token or "." not in token:
        return None
    raw, _, mac = token.partition(".")
    try:
        expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        payload = json.loads(_unb64(raw))
    except (ValueError, json.JSONDecodeError):
        return None
    issued = payload.get("iat")
    if not isinstance(issued, int):
        return None
    if (now if now is not None else time.time()) - issued > max_age:
        return None
    return payload


def identity_from(payload: dict | None) -> Identity | None:
    if not payload or not isinstance(payload.get("sub"), str) or not payload["sub"]:
        return None
    return Identity(payload["sub"], payload.get("email"), payload.get("name"), payload.get("picture"))


# ── PKCE ──────────────────────────────────────────────────────────────────────

def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) per RFC 7636, S256."""
    verifier = _b64(secrets.token_bytes(32))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


# ── the provider ─────────────────────────────────────────────────────────────

class Provider(Protocol):
    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str: ...

    def identity(self, code: str, redirect_uri: str, verifier: str) -> Identity:
        """Exchange the code and fetch who signed in. Raises AuthError."""
        ...


class GoogleProvider:
    def __init__(self, client_id: str, client_secret: str, http: httpx.Client | None = None) -> None:
        self.client_id, self.client_secret = client_id, client_secret
        self._http = http or httpx.Client(timeout=15.0)

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        return GOOGLE_AUTH + "?" + urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": "openid email profile", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    def identity(self, code: str, redirect_uri: str, verifier: str) -> Identity:
        try:
            token = self._http.post(GOOGLE_TOKEN, data={
                "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
            })
            if token.status_code != 200:
                raise AuthError("Google did not accept the sign-in. Try again.")
            access = token.json().get("access_token")
            if not access:
                raise AuthError("Google returned no access token.")
            info = self._http.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
            if info.status_code != 200:
                raise AuthError("Google would not say who signed in.")
        except httpx.HTTPError as exc:
            raise AuthError("Could not reach Google to sign you in.") from exc
        claims = info.json()
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthError("Google returned no subject.")
        if claims.get("email") and claims.get("email_verified") is False:
            raise AuthError("That Google account's email is not verified.")
        return Identity(sub, claims.get("email"), claims.get("name"), claims.get("picture"))


def allowed(identity: Identity, allow: tuple[str, ...]) -> bool:
    """With an allow-list, only those emails (or @domains) may sign in."""
    if not allow:
        return True
    email = (identity.email or "").lower()
    for entry in allow:
        entry = entry.lower().strip()
        if not entry:
            continue
        if entry.startswith("@") and email.endswith(entry):
            return True
        if email == entry:
            return True
    return False
