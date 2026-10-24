"""Beta kit: the beta invite from the waitlist (and its preview)."""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import admin, auth, beta
from app.api.main import app, database, jobs, rate_limits, repo
from app.notify import email as email_mod, templates

H = {"X-Requested-With": "voltage"}
ADA = "google:ada"


def _client(sub: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": sub, "email": f"{sub}@example.com", "name": sub, "picture": None}, "s3cret"))
    return client


@pytest.fixture()
def world(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret",
                                                  admin_owners=(ADA,), public_url="http://localhost:5173"))
    repo.reset()
    jobs.reset()
    rate_limits.reset()
    with database.tx() as c:
        c.execute("DELETE FROM waitlist")
        c.execute("DELETE FROM meta WHERE key LIKE 'beta_%'")
    yield {"ada": _client("ada"), "sam": _client("sam")}


def test_the_beta_invite_renders_for_a_waitlist_address_and_for_an_account():
    new = templates.render("beta_invite", public_url="https://v.example", name="Ann", credits=10, link="#login")
    assert new.subject == "You are in the Voltage beta" and "Make my account" in new.html and "10 beta credits" in new.text
    assert "Hi Ann," in new.text and "three short questions" in new.text and "https://v.example/#login" in new.text
    old = templates.render("beta_invite", public_url="https://v.example", credits=10, link="#home", existing=True)
    assert "Open Voltage" in old.html and "added your Voltage account" in old.text and "Make your account" not in old.text
    assert ("beta_invite", "Beta invite") in [(k, templates.LABELS[k]) for k in templates.KINDS]


def test_the_admin_preview_lists_the_beta_invite(world):
    kinds = world["ada"].get("/admin/emails/preview").json()["kinds"]
    assert {"kind": "beta_invite", "label": "Beta invite"} in kinds
    shown = world["ada"].get("/admin/emails/preview/beta_invite").json()
    assert shown["subject"] == "You are in the Voltage beta" and "Welcome to the beta" in shown["html"]


def test_invite_to_beta_marks_the_row_sends_the_beta_email_and_remembers_the_address(world):
    TestClient(app).post("/waitlist", json={"email": "cy@example.com", "name": "Cy"}, headers=H)
    ada = world["ada"]
    [row] = ada.get("/admin/waitlist").json()["rows"]
    assert row["beta"] is False
    assert world["sam"].post(f"/admin/waitlist/{row['id']}/invite", json={"beta": True}, headers=H).status_code == 404
    sent = ada.post(f"/admin/waitlist/{row['id']}/invite", json={"beta": True}, headers=H)
    assert sent.status_code == 200, sent.text
    assert sent.json()["row"]["status"] == "invited" and sent.json()["row"]["beta"] is True
    mail = email_mod.outbox(database, kind="beta_invite", to="cy@example.com")[-1]
    assert "Hi Cy," in mail["body"] and "http://localhost:5173/#login" in mail["body"] and mail["html"]
    assert email_mod.outbox(database, kind="waitlist_invite", to="cy@example.com") == []
    assert beta.pending_invite(database, "Cy@Example.com")
    assert ada.get("/admin/waitlist").json()["rows"][0]["beta"] is True
    assert any(a["action"] == "beta_invite" and a["target"] == "cy@example.com" for a in admin.recent_audit(database))
    # A plain Send invite still sends the access invite and is not a beta invite.
    TestClient(app).post("/waitlist", json={"email": "dee@example.com"}, headers=H)
    dee = next(r for r in ada.get("/admin/waitlist").json()["rows"] if r["email"] == "dee@example.com")
    assert ada.post(f"/admin/waitlist/{dee['id']}/invite", headers=H).status_code == 200
    assert email_mod.outbox(database, kind="waitlist_invite", to="dee@example.com") and not beta.pending_invite(database, "dee@example.com")
