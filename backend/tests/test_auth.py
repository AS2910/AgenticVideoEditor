"""Phase 9c: signed sessions, PKCE, the allow-list, and Google's answers."""
import httpx

from app.auth import (
    AuthError, GoogleProvider, Identity, allowed, identity_from, pkce_pair, sign, verify,
)


def test_a_signed_token_round_trips_and_a_tampered_or_stale_one_does_not():
    token = sign({"sub": "123", "email": "a@b.c"}, "secret", now=1000)
    assert verify(token, "secret", max_age=60, now=1030) == {"sub": "123", "email": "a@b.c", "iat": 1000}
    assert verify(token, "secret", max_age=60, now=1061) is None            # too old
    assert verify(token, "other", max_age=60, now=1030) is None             # wrong secret
    raw, _, mac = token.partition(".")
    assert verify(raw + "x." + mac, "secret", max_age=60, now=1030) is None  # altered
    assert verify(None, "secret", max_age=60) is None and verify("nodot", "secret", max_age=60) is None


def test_an_identity_needs_a_subject():
    assert identity_from({"sub": "9", "name": "A"}) == Identity("9", None, "A", None)
    assert identity_from({"email": "x"}) is None and identity_from(None) is None
    assert Identity("9").owner == "google:9"


def test_pkce_pairs_are_fresh_and_url_safe():
    v1, c1 = pkce_pair()
    v2, _ = pkce_pair()
    assert v1 != v2 and len(v1) >= 43 and "=" not in c1 and "+" not in c1


def test_the_allow_list_matches_emails_and_domains():
    me = Identity("1", "ash@example.com")
    assert allowed(me, ())
    assert allowed(me, ("ASH@example.com",)) and allowed(me, ("@example.com",))
    assert not allowed(me, ("@other.com", "someone@example.com"))
    assert not allowed(Identity("2", None), ("@example.com",))


def google(handler):
    transport = httpx.MockTransport(handler)
    return GoogleProvider("cid", "secret", http=httpx.Client(transport=transport))


def test_google_exchanges_the_code_then_asks_who_signed_in():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/token":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            assert body["code"] == "c0de" and body["code_verifier"] == "ver" and body["grant_type"] == "authorization_code"
            return httpx.Response(200, json={"access_token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"sub": "42", "email": "a@b.c", "email_verified": True, "name": "A", "picture": "p"})

    who = google(handler).identity("c0de", "http://x/cb", "ver")
    assert who == Identity("42", "a@b.c", "A", "p") and len(seen) == 2
    url = google(handler).authorize_url("http://x/cb", "st", "ch")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?") and "code_challenge=ch" in url and "state=st" in url


def test_google_failures_become_one_sentence():
    import pytest
    with pytest.raises(AuthError, match="did not accept"):
        google(lambda r: httpx.Response(400, json={})).identity("c", "u", "v")
    with pytest.raises(AuthError, match="Could not reach"):
        def down(r):
            raise httpx.ConnectError("no")
        google(down).identity("c", "u", "v")

    def unverified(r):
        if r.url.path == "/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"sub": "1", "email": "a@b.c", "email_verified": False})
    with pytest.raises(AuthError, match="not verified"):
        google(unverified).identity("c", "u", "v")
