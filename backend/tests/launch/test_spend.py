"""Launch item 3: spend protection. A global daily cap and an admin's kill
switch pause new paid work for everyone; the free trial and the per-user
ceilings hold on every paid path."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, flags, jobs, ledger, repo
from app.flags import ALL
from app.usage import PAUSED_WORDS, PaidPaused
from tests.api.test_endpoints import upload

H = {"X-Requested-With": "voltage"}


@pytest.fixture(autouse=True)
def fresh():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("launch.paid_paused", ALL)


def test_the_switch_pauses_new_paid_work_and_says_so(sample_video):
    client = TestClient(app)
    upload(client, sample_video)
    assert client.get("/status").json() == {"paid_paused": False, "message": None, "resumes_at": None}
    on = client.put("/admin/paid-pause", json={"paused": True}, headers=H)
    assert on.status_code == 200 and on.json()["paused"] and on.json()["reason"] == "switch"
    status = client.get("/status").json()
    assert status["paid_paused"] and status["message"] == PAUSED_WORDS
    with pytest.raises(PaidPaused):
        main._ensure_spend("p1")
    with pytest.raises(PaidPaused):
        main.budget.charge("p1", 10)                     # voicing inside a running turn stops too
    assert ledger.spent_usd("p1") == 0
    client.put("/admin/paid-pause", json={"paused": False}, headers=H)
    main._ensure_spend("p1")


def test_the_day_cap_pauses_until_midnight_utc(sample_video, monkeypatch):
    client = TestClient(app)
    upload(client, sample_video)
    monkeypatch.setattr(main, "settings", replace(main.settings, daily_cap_usd=1.0))
    ledger.record("p1", "anthropic", "agent", 100, "tokens", 0.6)
    assert not main.paid_state()["paused"]
    ledger.record("p1", "anthropic", "agent", 100, "tokens", 0.5)
    state = main.paid_state()
    assert state["paused"] and state["reason"] == "daily_cap" and state["resumes_at"].endswith("T00:00:00.000Z")
    spend = client.get("/admin/spend").json()
    assert spend["today_usd"] == 1.1 and spend["by_vendor"] == {"anthropic": 1.1} and spend["cap_usd"] == 1.0


def test_paid_paths_refuse_while_paused(sample_video, monkeypatch):
    client = TestClient(app)
    flags.set("launch.paid_paused", ALL, True)
    # An upload's transcription is paid with a real transcriber: refused before anything is stored.
    monkeypatch.setattr(main, "transcriber_label", "openai-whisper")
    refused = upload(client, sample_video)
    assert refused.status_code == 402 and refused.json()["detail"] == PAUSED_WORDS
    assert repo.list("local") == []
    # A2's text pass and D2's learned pass share one refusal.
    project = main.repo.get_project(client.post("/projects", json={"name": "P"}).json()["project_id"])
    assert PAUSED_WORDS in main._check_spend_refusal(project, 0.01)
    assert PAUSED_WORDS in main._batch_start_refusal(project, "local", 0.1)


def test_only_admins_see_the_spend_and_hold_the_switch(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=()))
    assert client.get("/admin/spend").status_code == 404
    assert client.put("/admin/paid-pause", json={"paused": True}, headers=H).status_code == 404
    assert not flags.enabled("launch.paid_paused")


def test_credits_hold_for_the_owner_level_paths(monkeypatch):
    """The trial's credits stop an upload's paid transcription too, not only turns."""
    from app import billing
    from app.usage import SpendCeilingReached
    billing.account(main.database, "local")
    monkeypatch.setattr(billing, "can_spend", lambda db, owner, f: (False, {"granted": 5.0, "used": 5.0}))
    with pytest.raises(SpendCeilingReached, match="credits are used up"):
        main._ensure_owner_spend("local")
