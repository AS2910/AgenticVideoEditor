"""Launch item 5: accounts with an email and a password. Sign up, confirm the
address, sign in, reset a forgotten password (other sessions signed out),
change the address, invite-only mode, and a deleted account made again
gets the sample again. Emails land in the fake outbox."""
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import auth
from app.api.main import app, database, flags, jobs, repo
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
    yield
    for flag in ("launch.invite_only", "golive.g1"):
        flags.clear(flag, ALL)


def _mail(kind: str, to: str) -> str:
    return email_mod.outbox(database, kind=kind, to=to)[-1]["body"]


def _link(body: str, pattern: str) -> str:
    return re.search(pattern, body).group(0)


def _signed_up(client: TestClient, email="ann@example.com") -> None:
    made = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "accept_terms": True}, headers=H)
    assert made.status_code == 201, made.text
    link = _link(_mail("verify_email", email), r"/api/auth/verify\?token=\S+")
    back = client.get(link.replace("/api", ""), follow_redirects=False)
    assert back.status_code == 302 and back.headers["location"].endswith("/#home")


def test_sign_up_confirm_and_sign_in():
    client = TestClient(app)
    assert client.get("/auth/options").json()["password"] is True
    refused = client.post("/auth/signup", json={"email": "ann@example.com", "password": PASSWORD}, headers=H)
    assert refused.status_code == 422 and "Accept the Terms" in refused.json()["detail"]
    weak = client.post("/auth/signup", json={"email": "ann@example.com", "password": "short", "accept_terms": True}, headers=H)
    assert weak.status_code == 422 and "at least 10 characters" in weak.json()["detail"]
    client.post("/auth/signup", json={"email": "Ann@Example.com", "password": PASSWORD, "accept_terms": True}, headers=H)
    # Not confirmed yet: no sign-in.
    early = client.post("/auth/password/login", json={"email": "ann@example.com", "password": PASSWORD}, headers=H)
    assert early.status_code == 403 and early.json()["detail"]["code"] == "unverified"
    link = _link(_mail("verify_email", "ann@example.com"), r"/api/auth/verify\?token=\S+")
    assert client.get(link.replace("/api", ""), follow_redirects=False).status_code == 302
    me = client.get("/auth/me").json()["user"]
    assert me["email"] == "ann@example.com" and me["provider"] == "acct"
    account = store.by_email(database, "ann@example.com")
    with database.tx() as c:
        terms = c.execute("SELECT terms_version, terms_at FROM accounts WHERE id = ?", (account.id,)).fetchone()
    assert terms["terms_version"] and terms["terms_at"]
    # The link works once.
    assert "used already" in client.get(link.replace("/api", ""), follow_redirects=False).headers["location"].replace("%20", " ")
    fresh = TestClient(app)
    wrong = fresh.post("/auth/password/login", json={"email": "ann@example.com", "password": "wrong password!"}, headers=H)
    assert wrong.status_code == 401 and wrong.json()["detail"] == "That email and password do not match an account."
    nobody = fresh.post("/auth/password/login", json={"email": "nobody@example.com", "password": PASSWORD}, headers=H)
    assert nobody.json() == wrong.json()                                   # no telling who has an account
    assert fresh.post("/auth/password/login", json={"email": "ann@example.com", "password": PASSWORD}, headers=H).status_code == 200
    assert fresh.get("/auth/me").json()["user"]["email"] == "ann@example.com"


def test_signing_up_twice_tells_the_owner_of_the_address_not_the_caller():
    client = TestClient(app)
    _signed_up(client)
    again = TestClient(app).post("/auth/signup", json={"email": "ann@example.com", "password": PASSWORD + "x", "accept_terms": True}, headers=H)
    assert again.status_code == 201 and again.json()["sent"]
    assert "already has one" in _mail("account_exists", "ann@example.com")


def test_a_forgotten_password_is_reset_and_other_sessions_end():
    phone, laptop = TestClient(app), TestClient(app)
    _signed_up(phone)
    laptop.post("/auth/password/login", json={"email": "ann@example.com", "password": PASSWORD}, headers=H)
    assert laptop.get("/auth/me").json()["user"]
    asked = TestClient(app).post("/auth/password/forgot", json={"email": "ann@example.com"}, headers=H)
    unknown = TestClient(app).post("/auth/password/forgot", json={"email": "who@example.com"}, headers=H)
    assert asked.json() == unknown.json()
    token = re.search(r"#reset/(\S+)", _mail("password_reset", "ann@example.com")).group(1)
    reset = TestClient(app)
    done = reset.post("/auth/password/reset", json={"token": token, "password": "a brand new password"}, headers=H)
    assert done.status_code == 200 and reset.get("/auth/me").json()["user"]["email"] == "ann@example.com"
    assert phone.get("/auth/me").json()["user"] is None and laptop.get("/auth/me").json()["user"] is None
    assert reset.post("/auth/password/reset", json={"token": token, "password": "another new password"}, headers=H).status_code == 422
    assert TestClient(app).post("/auth/password/login", json={"email": "ann@example.com", "password": "a brand new password"},
                                headers=H).status_code == 200


def test_the_address_changes_only_from_a_link_sent_to_it():
    client = TestClient(app)
    _signed_up(client)
    owner = store.by_email(database, "ann@example.com").owner
    wrong = client.post("/auth/change-email", json={"new_email": "ann@new.example", "password": "not my password"}, headers=H)
    assert wrong.status_code == 422 and wrong.json()["detail"] == "That password is not right."
    sent = client.post("/auth/change-email", json={"new_email": "ann@new.example", "password": PASSWORD}, headers=H)
    assert sent.status_code == 200 and "ann@new.example" in sent.json()["message"]
    assert "ann@new.example" in _mail("change_email_notice", "ann@example.com")
    assert store.by_email(database, "ann@example.com") is not None                 # nothing changed yet
    link = _link(_mail("change_email", "ann@new.example"), r"/api/auth/change-email/confirm\?token=\S+")
    client.get(link.replace("/api", ""), follow_redirects=False)
    account = store.by_email(database, "ann@new.example")
    assert account is not None and account.owner == owner                           # the owner id never moves
    assert client.get("/auth/me").json()["user"]["email"] == "ann@new.example"


def test_invite_only_needs_an_invite_or_a_code(monkeypatch):
    flags.set("launch.invite_only", ALL, True)
    monkeypatch.setenv("AVE_INVITE_CODES", "LAUNCH-42")
    client = TestClient(app)
    assert client.get("/auth/options").json()["invite_only"] is True
    no = client.post("/auth/signup", json={"email": "bo@example.com", "password": PASSWORD, "accept_terms": True}, headers=H)
    assert no.status_code == 403 and "invite-only" in no.json()["detail"]
    yes = client.post("/auth/signup", json={"email": "bo@example.com", "password": PASSWORD, "accept_terms": True,
                                            "invite_code": "LAUNCH-42"}, headers=H)
    assert yes.status_code == 201
    # A waiting workspace invite for the address lets them in too.
    from app.store import members as members_store
    from app.store.workspaces import personal
    with database.tx() as c:
        wid = personal(c, "google:owner")
    members_store.invite(database, main.share_key, wid, "cy@example.com", "editor", "google:owner")
    invited = client.post("/auth/signup", json={"email": "cy@example.com", "password": PASSWORD, "accept_terms": True}, headers=H)
    assert invited.status_code == 201


def test_a_deleted_account_made_again_gets_the_sample_again():
    flags.set("golive.g1", ALL, True)
    client = TestClient(app)
    _signed_up(client)
    owner = store.by_email(database, "ann@example.com").owner
    assert main.repo.get_meta(f"sample:{owner}")
    assert client.delete("/account", headers=H).status_code == 204
    assert store.by_email(database, "ann@example.com") is None and not main.repo.get_meta(f"sample:{owner}")
    again = TestClient(app)
    _signed_up(again)
    new_owner = store.by_email(database, "ann@example.com").owner
    record = main.repo.get_meta(f"sample:{new_owner}")
    assert record and '"project_id": null' not in record                            # made, not skipped


def test_a_session_from_a_deleted_account_is_refused():
    client = TestClient(app)
    _signed_up(client)
    account = store.by_email(database, "ann@example.com")
    store.delete(database, account.id)
    assert client.get("/auth/me").json()["user"] is None
    forged = TestClient(app)
    forged.cookies.set(auth.SESSION_COOKIE, auth.sign({"sub": "nope", "provider": "acct", "sv": 1}, main.settings.session_secret))
    assert forged.get("/videos").status_code == 401
