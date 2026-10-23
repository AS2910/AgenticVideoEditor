"""Launch item 5: every state-changing route refuses a request that carries
the session cookie but not the header a cross-site form cannot set
(`X-Requested-With: voltage`). Parametrised over the app's route table, so
a write route added later without the check fails here.

SameSite=Lax already keeps the cookie off cross-site POSTs in current
browsers; the header is the second lock (older browsers, same-site
subdomains, and a top-level GET that changes nothing anyway)."""
from __future__ import annotations

from dataclasses import replace

import pytest

import app.api.main as main
from app.flags import KNOWN
from tests.launch.test_isolation import _all_routes, _client, _fill, _request_kwargs

ME = "google:cara"
WRITES = {"POST", "PUT", "PATCH", "DELETE"}

# Write routes that carry no session cookie by design, each with why.
NO_COOKIE = {
    "POST /billing/webhooks/stripe": "Stripe calls it; the signature is the check",
    "POST /billing/webhooks/razorpay": "Razorpay calls it; the signature is the check",
}


def _cases():
    seen = set()
    for route in _all_routes():
        for method in sorted(route.methods & WRITES):
            key = f"{method} {route.path}"
            if key in seen:
                continue
            seen.add(key)
            yield pytest.param(method, route, id=key)


@pytest.fixture(scope="module")
def signed_in():
    mp = pytest.MonkeyPatch()
    mp.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret"))
    for flag in KNOWN:
        if not flag.startswith("launch."):
            main.flags.set(flag, ME, True)
    yield _client("cara")
    mp.undo()
    for flag in KNOWN:
        main.flags.clear(flag, ME)


IDS = {"video": "v-nope", "folder": "p-nope", "spare": "v-nope2"}


@pytest.mark.parametrize("method,route", list(_cases()))
def test_a_write_without_the_header_is_refused(signed_in, method, route):
    key = f"{method} {route.path}"
    path = _fill(route.path, IDS, route)
    resp = signed_in.request(method, path, **_request_kwargs(route))
    if key in NO_COOKIE:
        assert "did not come from Voltage" not in resp.text, key
        return
    assert resp.status_code == 403 and "did not come from Voltage" in resp.text, \
        f"{key} -> {resp.status_code}: {resp.text[:200]}"


def test_the_no_cookie_list_names_real_routes():
    keys = {f"{m} {r.path}" for r in _all_routes() for m in r.methods}
    assert set(NO_COOKIE) <= keys, set(NO_COOKIE) - keys


def test_the_same_writes_pass_the_check_with_the_header(signed_in):
    ok = signed_in.post("/workspace/switch", json={"workspace_id": None}, headers={"X-Requested-With": "voltage"})
    assert ok.status_code == 200
    assert signed_in.post("/auth/logout", headers={"X-Requested-With": "voltage"}).status_code == 200


def test_a_cross_site_invite_accept_cannot_pull_someone_into_a_workspace(signed_in):
    """A page elsewhere posting to /invites/<attacker's token>/accept would have
    made the visitor a member of the attacker's workspace (and switched them
    into it, so their next upload landed there)."""
    resp = signed_in.post("/invites/anything/accept")
    assert resp.status_code == 403 and resp.json()["code"] == "csrf"


def test_an_admin_switch_needs_the_header(signed_in, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=(ME,)))
    assert signed_in.put("/admin/paid-pause", json={"paused": True}).status_code == 403
    assert not main.flags.enabled("launch.paid_paused")


def test_with_sign_in_off_nothing_changes(monkeypatch):
    """Local mode has no cookie to ride, so the header is not asked for."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="off"))
    assert TestClient(main.app).post("/workspace/switch", json={"workspace_id": None}).status_code != 403
