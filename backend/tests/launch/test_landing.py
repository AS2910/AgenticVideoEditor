"""Launch item 8: the public pricing the landing page reads, Request access
(stored once per address, the same answer whatever the address, rate
limited), the admin's waitlist and its Send invite, which lets the address
sign up while invite-only is on."""
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, database, flags, jobs, rate_limits, repo
from app.billing import prices
from app.flags import ALL
from app.notify import email as email_mod
from app.store import accounts as store

H = {"X-Requested-With": "voltage"}
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def accounts_on(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="accounts", session_secret="s3cret" * 6,
                                                  public_url="http://localhost:5173"))
    repo.reset()
    jobs.reset()
    rate_limits.reset()
    with database.tx() as c:
        c.execute("DELETE FROM waitlist")
    yield
    rate_limits.reset()
    flags.clear("launch.invite_only", ALL)


def _signed_up(client: TestClient, email: str) -> str:
    made = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "accept_terms": True}, headers=H)
    assert made.status_code == 201, made.text
    body = email_mod.outbox(database, kind="verify_email", to=email)[-1]["body"]
    link = re.search(r"/api/auth/verify\?token=\S+", body).group(0)
    assert client.get(link.replace("/api", ""), follow_redirects=False).status_code == 302
    return store.by_email(database, email).owner


def test_pricing_is_public_and_read_from_the_billing_config():
    got = TestClient(app).get("/pricing")
    assert got.status_code == 200
    body = got.json()
    assert body["trial_credits"] == prices.TRIAL_CREDITS
    assert [(p["plan_id"], p["usd"], p["inr"], p["credits"]) for p in body["plans"]] == [
        (p.plan_id, p.usd, p.inr, p.credits) for p in prices.PLANS.values()]
    assert [t["credits"] for t in body["topups"]] == list(prices.TOPUPS)
    assert body["topups"][0]["usd"] == round(prices.TOPUPS[0] * prices.TOPUP_MARKUP, 2)
    assert body["topup_months"] == prices.TOPUP_MONTHS
    assert body["test_mode"] is True and body["invite_only"] is False


def test_request_access_is_stored_once_and_answers_the_same_for_every_address():
    client = TestClient(app)
    first = client.post("/waitlist", json={"email": "Bo@Example.com", "name": "Bo", "use_case": "cooking shorts"}, headers=H)
    assert first.status_code == 201
    again = client.post("/waitlist", json={"email": "bo@example.com", "name": "Someone else"}, headers=H)
    assert again.json() == first.json()
    _signed_up(client, "has@example.com")
    taken = TestClient(app).post("/waitlist", json={"email": "has@example.com"}, headers=H)
    assert taken.status_code == 201 and taken.json() == first.json()      # no telling who has an account
    with database.tx() as c:
        rows = [dict(r) for r in c.execute("SELECT email, name, use_case FROM waitlist ORDER BY id")]
    assert rows[0] == {"email": "bo@example.com", "name": "Bo", "use_case": "cooking shorts"}   # the first ask stays
    assert len(rows) == 2
    bad = client.post("/waitlist", json={"email": "not an address"}, headers=H)
    assert bad.status_code == 422
    assert client.post("/waitlist", json={"email": "x@example.com"}).status_code == 403       # no CSRF header


def test_request_access_is_rate_limited_per_caller():
    client = TestClient(app)
    for n in range(5):
        assert client.post("/waitlist", json={"email": f"p{n}@example.com"}, headers=H).status_code == 201
    over = client.post("/waitlist", json={"email": "p9@example.com"}, headers=H)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited"


def test_admin_lists_the_waitlist_and_an_invite_lets_the_address_sign_up_while_invite_only(monkeypatch):
    flags.set("launch.invite_only", ALL, True)
    # The admin signs up before invite-only matters for them (a code).
    monkeypatch.setenv("AVE_INVITE_CODES", "ADMIN-1")
    admin = TestClient(app)
    made = admin.post("/auth/signup", json={"email": "admin@example.com", "password": PASSWORD, "accept_terms": True,
                                            "invite_code": "ADMIN-1"}, headers=H)
    assert made.status_code == 201
    body = email_mod.outbox(database, kind="verify_email", to="admin@example.com")[-1]["body"]
    admin.get(re.search(r"/api/auth/verify\?token=\S+", body).group(0).replace("/api", ""), follow_redirects=False)
    admin_owner = store.by_email(database, "admin@example.com").owner
    monkeypatch.setenv("AVE_INVITE_CODES", "")

    public = TestClient(app)
    public.post("/waitlist", json={"email": "cy@example.com", "name": "Cy"}, headers=H)
    refused = public.post("/auth/signup", json={"email": "cy@example.com", "password": PASSWORD, "accept_terms": True}, headers=H)
    assert refused.status_code == 403                                       # waiting is not invited

    # Not an admin yet: the list is not there.
    assert admin.get("/admin/waitlist").status_code == 404
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=(admin_owner,)))
    listed = admin.get("/admin/waitlist").json()
    [row] = listed["rows"]
    assert row["email"] == "cy@example.com" and row["status"] == "waiting" and listed["invite_only"] is True
    assert public.get("/admin/waitlist").status_code == 401
    assert admin.post(f"/admin/waitlist/{row['id']}/invite").status_code == 403     # no CSRF header
    assert admin.post("/admin/waitlist/99999/invite", headers=H).status_code == 404

    sent = admin.post(f"/admin/waitlist/{row['id']}/invite", headers=H)
    assert sent.status_code == 200
    invited = sent.json()["row"]
    assert invited["status"] == "invited" and invited["invited_by"] == admin_owner and invited["invited_at"]
    mail = email_mod.outbox(database, kind="waitlist_invite", to="cy@example.com")[-1]
    assert mail["html"] and "Make my account" in mail["html"]              # item 9's access invite template
    from app import admin as admin_mod
    assert any(a["action"] == "waitlist_invite" and a["target"] == "cy@example.com"
               for a in admin_mod.recent_audit(database))                         # item 10: in the audit trail
    assert "Hi Cy," in mail["body"] and "http://localhost:5173/#login" in mail["body"]

    joined = public.post("/auth/signup", json={"email": "Cy@Example.com", "password": PASSWORD, "accept_terms": True}, headers=H)
    assert joined.status_code == 201, joined.text
    assert store.by_email(database, "cy@example.com") is not None
    # Someone else on the list but not invited is still refused.
    public.post("/waitlist", json={"email": "dee@example.com"}, headers=H)
    assert public.post("/auth/signup", json={"email": "dee@example.com", "password": PASSWORD, "accept_terms": True},
                       headers=H).status_code == 403
