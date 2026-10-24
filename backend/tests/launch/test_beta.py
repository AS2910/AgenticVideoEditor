"""Beta kit: the beta invite from the waitlist (and its preview); the cohort:
its flags on, $10 of credits once per person, joined by an admin or at the
first sign-in of an address invited to the beta; the welcome checklist; the
three questions, once, after a first export; the admin's Beta view."""
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
        c.execute("DELETE FROM beta_survey")
        c.execute("DELETE FROM beta_feedback")
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


def test_the_welcome_checklist_takes_known_issues_and_feedback_is_ticked_by_sending_it(world, monkeypatch):
    from app import beta_feedback_api
    monkeypatch.setattr(beta_feedback_api, "sends", beta_feedback_api.RateLimit(10, 3600.0))
    sam = world["sam"]
    main.repo.set_meta("onboarding:google:sam", "{}")
    put = sam.put("/me/onboarding", json={"checklist": ["known-issues", "nope"]}, headers=H)
    assert put.status_code == 200 and put.json()["checklist"] == ["known-issues"]
    assert sam.post("/beta-feedback", data={"message": "The badge is nice."}, headers=H).status_code == 201
    assert sam.get("/me/onboarding").json()["checklist"] == ["known-issues", "feedback"]


def _exported(owner: str) -> None:
    main.analytics.track("video_exported", owner, {"video_id": "v1", "seconds": 4.0})
    main.analytics.track("first_export", owner, {"video_id": "v1"})


def test_the_three_questions_are_shown_once_after_the_first_export_to_the_cohort(world):
    sam = world["sam"]
    with database.tx() as c:
        c.execute("DELETE FROM analytics_events WHERE owner = 'google:sam'")
    got = sam.get("/me/beta-survey").json()
    assert got["due"] is False and [q["id"] for q in got["questions"]] == ["useful", "almost_stopped", "would_pay"]
    _exported("google:sam")
    assert sam.get("/me/beta-survey").json()["due"] is False                     # not in the cohort
    assert sam.post("/me/beta-survey", json={"useful": "very", "would_pay": "yes"}, headers=H).status_code == 404
    beta.join(database, main.flags, "google:sam")
    assert sam.get("/me/beta-survey").json()["due"] is True
    assert sam.post("/me/beta-survey/shown", json={"video_id": "nope"}, headers=H).json() == {"due": False}
    assert sam.get("/me/beta-survey").json()["due"] is False                     # shown once, answered or not
    assert sam.post("/me/beta-survey", json={"useful": "maybe", "would_pay": "yes"}, headers=H).status_code == 422
    out = sam.post("/me/beta-survey", json={"useful": "somewhat", "almost_stopped": "  The upload\n was slow ",
                                            "would_pay": "maybe"}, headers=H)
    assert out.status_code == 201 and out.json()["said"] == beta.THANKS
    row = beta.survey_row(database, "google:sam")
    assert (row["useful"], row["almost_stopped"], row["would_pay"], row["video_id"]) == ("somewhat", "The upload was slow", "maybe", None)
    again = sam.post("/me/beta-survey", json={"useful": "very", "would_pay": "yes"}, headers=H)
    assert again.status_code == 409 and beta.survey_row(database, "google:sam")["useful"] == "somewhat"


def test_opening_the_export_page_counts_as_an_export_for_the_questions(world):
    owner = "google:pat"
    beta.join(database, main.flags, owner)
    assert not beta.survey_due(database, main.flags, owner, owner)
    main.repo.set_meta(f"onboarding:{owner}", '{"checklist": ["export"]}')
    assert beta.survey_due(database, main.flags, owner, owner)


def test_the_admin_beta_view_has_each_person_with_activity_spend_feedback_and_errors(world, monkeypatch):
    from app import beta_feedback_api
    monkeypatch.setattr(beta_feedback_api, "sends", beta_feedback_api.RateLimit(10, 3600.0))
    ada, sam = world["ada"], world["sam"]
    assert sam.get("/admin/beta").status_code == 404
    main.email_mod.remember_address(database, "google:sam", "sam@example.com")
    with database.tx() as c:
        c.execute("DELETE FROM analytics_events WHERE owner = 'google:sam'")
        c.execute("DELETE FROM error_reports WHERE owner = 'google:sam'")
        c.execute("INSERT INTO error_reports (owner, source, message, at) VALUES ('google:sam', 'client', 'Boom', ?)",
                  (main.now_iso(),))
    assert ada.post("/admin/beta/join", json={"who": "google:sam", "email": False}, headers=H).json()["emailed"] is False
    _exported("google:sam")
    assert sam.post("/beta-feedback", data={"message": "Lovely, but slow."}, headers=H).status_code == 201
    sam.post("/me/beta-survey", json={"useful": "very", "would_pay": "no"}, headers=H)
    view = ada.get("/admin/beta").json()
    person = next(p for p in view["people"] if p["owner"] == "google:sam")
    assert person["emails"] == ["sam@example.com"] and person["exports"] == 1 and person["credits_given"] == 10.0
    assert person["spend_usd"] == 0.0 and person["last_active"]
    assert person["feedback"] == {"messages": 1, "latest": "Lovely, but slow."}
    assert person["errors"] == {"count": 1, "latest": "Boom"}
    assert person["survey"]["useful"] == "very" and person["survey"]["would_pay"] == "no"
    assert view["survey"]["answered"] == 1 and view["survey"]["useful"]["very"] == 1 and view["survey"]["would_pay"]["no"] == 1
    assert view["credits_each"] == 10.0
