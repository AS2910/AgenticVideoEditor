"""Beta kit: the beta invite from the waitlist (and its preview); the cohort:
its flags on, $10 of credits once per person, joined by an admin or at the
first sign-in of an address invited to the beta."""
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
        c.execute("DELETE FROM feature_flags WHERE flag LIKE 'beta.%' OR (flag IN ('projects.batch', 'projects.review') AND owner <> '*')")
        c.execute("DELETE FROM credit_grants WHERE reference = 'Given by Voltage: beta'")
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


def _beta_grants(owner: str) -> list[dict]:
    with database.tx() as c:
        return [dict(r) for r in c.execute("SELECT kind, credits, reference FROM credit_grants WHERE owner = ? "
                                           "AND reference = 'Given by Voltage: beta'", (owner,))]


def test_the_cohort_flag_is_off_by_default_even_for_the_default_owner():
    assert main.flags.enabled(beta.COHORT, "local") is False
    assert main.flags.enabled("beta.anything", "google:nobody") is False
    from app.flags import is_known
    assert is_known(beta.COHORT)


def test_joining_turns_on_b_and_c_and_grants_ten_credits_once(world):
    owner = "google:cohort1"
    assert not beta.in_cohort(main.flags, owner)
    assert not main.flags.enabled("projects.batch", owner) and not main.flags.enabled("projects.review", owner)
    first = beta.join(database, main.flags, owner)
    assert first == {"joined": True, "granted": True, "credits": 10.0}
    assert beta.in_cohort(main.flags, owner)
    on = main.flags.enabled_for(owner)
    assert {"beta.cohort", "projects.batch", "projects.review"} <= set(on)
    assert _beta_grants(owner) == [{"kind": "admin", "credits": 10.0, "reference": "Given by Voltage: beta"}]
    # Again: nothing more is given.
    assert beta.join(database, main.flags, owner) == {"joined": False, "granted": False, "credits": 0.0}
    assert len(_beta_grants(owner)) == 1
    # Out of the cohort and back in (an admin's Features toggle): still once per person.
    main.flags.set(beta.COHORT, owner, False)
    assert beta.join(database, main.flags, owner)["granted"] is False and len(_beta_grants(owner)) == 1
    assert owner in [r["owner"] for r in beta.cohort(database)]
    from app import billing
    left = billing.credits(database, owner, lambda at: 0.0)
    assert left["left"] == pytest.approx(billing.TRIAL_CREDITS + 10.0)


def test_a_failed_grant_can_be_tried_again(world, monkeypatch):
    from app import billing
    owner = "google:cohort2"

    def broken(*a, **k):
        raise billing.BillingError("down")
    monkeypatch.setattr(billing, "admin_grant", broken)
    with pytest.raises(billing.BillingError):
        beta.join(database, main.flags, owner)
    monkeypatch.undo()
    assert beta.join(database, main.flags, owner)["granted"] is True and len(_beta_grants(owner)) == 1


def test_an_admin_adds_a_person_by_address_and_they_get_the_beta_email(world):
    sam = world["sam"]
    main.email_mod.remember_address(database, "google:sam", "sam@example.com")     # as a Google sign-in does
    ada = world["ada"]
    assert sam.post("/admin/beta/join", json={"who": "sam@example.com"}, headers=H).status_code == 404
    assert ada.post("/admin/beta/join", json={"who": "nobody@example.com"}, headers=H).status_code == 404
    out = ada.post("/admin/beta/join", json={"who": "sam@example.com"}, headers=H)
    assert out.status_code == 200, out.text
    assert out.json() == {"owner": "google:sam", "joined": True, "granted": True, "credits": 10.0, "emailed": True}
    mail = email_mod.outbox(database, kind="beta_invite", to="sam@example.com")[-1]
    assert "Open Voltage" in mail["html"] and "http://localhost:5173/#home" in mail["body"]
    assert "beta.cohort" in sam.get("/me/flags").json()["flags"]
    again = ada.post("/admin/beta/join", json={"who": "google:sam"}, headers=H).json()
    assert again["joined"] is False and again["granted"] is False and again["emailed"] is False
    assert len(_beta_grants("google:sam")) == 1
    assert [a["action"] for a in admin.recent_audit(database, target="google:sam")][:2] == ["beta_join", "beta_join"]


def test_an_address_invited_to_the_beta_joins_at_its_first_sign_in(world):
    owner = "google:newbie"
    beta.mark_invited(database, "Newbie@example.com")
    main.email_mod.remember_address(database, owner, "newbie@example.com")
    main._funnel_started.discard(owner)
    main._signed_in(owner)
    assert beta.in_cohort(main.flags, owner) and len(_beta_grants(owner)) == 1
    # Someone not invited does not.
    main.email_mod.remember_address(database, "google:other", "other@example.com")
    main._funnel_started.discard("google:other")
    main._signed_in("google:other")
    assert not beta.in_cohort(main.flags, "google:other")
