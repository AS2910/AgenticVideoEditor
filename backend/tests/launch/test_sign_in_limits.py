"""Run 4 item 4a: the sign-in limit is per account and address, with a looser
ceiling per address. An office behind one address can sign up and sign in
together; one account guessed from one address is still stopped; one address
trying many accounts meets the ceiling. TestClient calls all come from one
address ("testclient")."""
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app
from app.ratelimit import Limits
from tests.launch.test_accounts import H, PASSWORD, _link, _mail, accounts_on  # noqa: F401 - the fixture


def test_ten_people_behind_one_address_all_sign_up_and_sign_in():
    for n in range(10):
        email = f"person{n}@office.example"
        client = TestClient(app)
        made = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "accept_terms": True}, headers=H)
        assert made.status_code == 201, (n, made.text)
        link = _link(_mail("verify_email", email), r"/api/auth/verify\?token=\S+")
        assert client.get(link.replace("/api", ""), follow_redirects=False).status_code == 302, n
        later = TestClient(app).post("/auth/password/login", json={"email": email, "password": PASSWORD}, headers=H)
        assert later.status_code == 200, (n, later.text)


def test_one_account_guessed_from_one_address_is_stopped():
    client = TestClient(app)
    guess = {"email": "ann@example.com", "password": "not the password"}
    for _ in range(20):
        assert client.post("/auth/password/login", json=guess, headers=H).status_code == 401
    over = client.post("/auth/password/login", json=guess, headers=H)
    assert over.status_code == 429 and over.json()["detail"].startswith("Too many sign-in attempts from here.")
    # The address has room left for someone else in the office.
    other = client.post("/auth/password/login", json={"email": "bob@example.com", "password": "nope nope nope"}, headers=H)
    assert other.status_code == 401
    # Capitals and spaces do not make a fresh bucket.
    same = client.post("/auth/password/login", json={"email": " ANN@example.com", "password": "x" * 12}, headers=H)
    assert same.status_code == 429


def test_one_address_trying_many_accounts_meets_the_ceiling():
    client = TestClient(app)
    for n in range(100):
        got = client.post("/auth/password/login", json={"email": f"user{n}@example.com", "password": "guess guess"}, headers=H)
        assert got.status_code == 401, n
    over = client.post("/auth/password/login", json={"email": "user100@example.com", "password": "guess guess"}, headers=H)
    assert over.status_code == 429


def test_the_buckets_by_hand():
    clock = [0.0]
    limits = Limits(clock=lambda: clock[0])
    assert limits.keys_by_account("POST", "/api/auth/password/login") and not limits.keys_by_account("POST", "/videos")
    for _ in range(20):
        assert limits.check("POST", "/auth/password/login", None, "1.1.1.1", "ann@x.com") is None
    assert limits.check("POST", "/auth/password/login", None, "1.1.1.1", "ann@x.com") == "auth"
    assert limits.check("POST", "/auth/password/login", None, "2.2.2.2", "ann@x.com") is None   # per address too
    # 20 of the 100 used above (the refused one is not counted); no account: the ceiling only.
    for _ in range(80):
        assert limits.check("GET", "/auth/login", None, "1.1.1.1") is None
    assert limits.check("GET", "/auth/login", None, "1.1.1.1") == "auth_ip"
    clock[0] += 601
    assert limits.check("POST", "/auth/password/login", None, "1.1.1.1", "ann@x.com") is None


def test_a_forged_forwarded_header_does_not_change_the_address(monkeypatch):
    """The app reads only the peer address (nginx sets it, trusting Caddy alone), so a
    client's own X-Forwarded-For makes no fresh bucket."""
    monkeypatch.setattr(main, "rate_limits", Limits())
    client = TestClient(app)
    guess = {"email": "ann@example.com", "password": "not the password"}
    for n in range(20):
        client.post("/auth/password/login", json=guess, headers={**H, "X-Forwarded-For": f"10.0.0.{n}"})
    over = client.post("/auth/password/login", json=guess, headers={**H, "X-Forwarded-For": "10.9.9.9"})
    assert over.status_code == 429
