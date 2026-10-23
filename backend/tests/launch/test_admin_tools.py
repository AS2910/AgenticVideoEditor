"""Launch rehearsal item 10: admin tools for launch day.

Sign-in is on. Ada is the admin; Sam owns a workspace with Mo as an Editor;
Bo is nobody special. Every /admin route answers 404 to Bo and to Sam; Ada
finds Sam by part of an address, reads his workspace, spend, credits, jobs
and errors, grants credits (with a reason), refunds a payment and reverses
credits, suspends him (403 everywhere for Sam and for Mo in Sam's workspace,
sign-ins refused, share and media links stopped, running jobs cancelled,
paid steps refused) and unsuspends him (everything back). Each action is one
append-only row in the audit trail.
"""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import admin, auth, billing
from app.api.main import app, database, flags, jobs, repo
from app.flags import ALL, KNOWN
from app.notify import email as email_mod
from app.store import members as members_store

H = {"X-Requested-With": "voltage"}
ADA, SAM, MO, BO = "google:ada", "google:sam", "google:mo", "google:bo"


_START = [0]


def _trail(target: str | None = None) -> list[dict]:
    """This test's audit rows, newest first (the trail is append-only, so earlier tests' rows stay)."""
    return [r for r in admin.recent_audit(database, 200, target=target) if r["id"] > _START[0]]


def _client(sub: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": sub, "email": f"{sub}@example.com", "name": sub, "picture": None}, "s3cret"))
    return client


@pytest.fixture()
def world(monkeypatch, sample_video):
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret",
                                                  admin_owners=(ADA,)))
    repo.reset()
    jobs.reset()
    with database.tx() as c:
        c.execute("DELETE FROM suspensions")
    for who in (ADA, SAM, MO, BO, "local"):
        for flag in KNOWN:
            if not flag.startswith("launch."):
                flags.set(flag, who, True)
    sam, mo = _client("sam"), _client("mo")
    email_mod.remember_address(database, SAM, "Sam.Smith@Example.com")
    email_mod.remember_address(database, ADA, "ada@example.com")
    with database.tx() as c:
        _START[0] = int(c.execute("SELECT COALESCE(MAX(id), 0) FROM admin_audit").fetchone()[0])
    with open(sample_video, "rb") as handle:
        made = sam.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H)
    assert made.status_code == 200, made.text
    video = made.json().get("video_id") or made.json()["project_id"]
    out = sam.post("/workspace/invites", json={"email": "mo@example.com", "role": "editor"}, headers=H)
    assert out.status_code == 201, out.text
    [mail] = email_mod.outbox(database, kind="workspace_invite", to="mo@example.com")
    token = re.search(r"#invite/(\S+)", mail["body"]).group(1)
    joined = mo.post(f"/invites/{token}/accept", headers=H)
    assert joined.status_code == 200, joined.text
    mo.cookies.set("ave_workspace", joined.json()["workspace_id"])
    yield {"ada": _client("ada"), "sam": sam, "mo": mo, "bo": _client("bo"), "video": video}
    for who in (ADA, SAM, MO, BO, "local"):
        for flag in KNOWN:
            flags.clear(flag, who)
    flags.clear("launch.paid_paused", ALL)
    with database.tx() as c:
        c.execute("DELETE FROM suspensions")


def _admin_routes():
    from tests.launch.test_isolation import _all_routes
    for route in _all_routes():
        if route.path.startswith("/admin"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path


def test_every_admin_route_is_404_to_everyone_else(world):
    found = list(_admin_routes())
    assert {("GET", "/admin/users"), ("POST", "/admin/users/{owner}/suspend"), ("GET", "/admin/audit")} <= set(found)
    for client in (world["bo"], world["sam"], world["mo"]):
        for method, path in found:
            path = re.sub(r"{\w+}", SAM, re.sub(r"{\w+_id}", "1", path))
            resp = client.request(method, path, headers=H, params={"owner": SAM}, json={"reason": "because", "credits": 1, "paused": True,
                                                                 "owner": SAM, "flag": "golive.g3", "invoice_id": 1})
            assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
    assert not admin.suspension(database, SAM)


def test_an_admin_finds_someone_by_part_of_an_address(world):
    from app.store import accounts as accounts_store
    acct, _ = accounts_store.sign_up(database, "pat@shop.example", "a-long-password")
    email_mod.remember_address(database, "email:lee@shop.example", "lee@shop.example")
    ada = world["ada"]
    users = ada.get("/admin/users", params={"q": "SMITH@exam"}).json()["users"]
    assert [u["owner"] for u in users] == [SAM] and users[0]["emails"] == ["sam.smith@example.com"]
    shop = {u["owner"]: u for u in ada.get("/admin/users", params={"q": "shop.ex"}).json()["users"]}
    assert set(shop) == {acct.owner, "email:lee@shop.example"} and shop[acct.owner]["kind"] == "password"
    members = ada.get("/admin/users", params={"q": "mo@exa"}).json()["users"]
    assert [u["owner"] for u in members] == [MO]
    assert ada.get("/admin/users", params={"q": "x"}).json()["users"] == []


def test_the_user_view_shows_workspace_spend_credits_jobs_and_errors(world):
    main.ledger.record(world["video"], "elevenlabs", "speech", 100, "characters", 0.25)
    main.activity.create(world["video"], "export")
    failed = main.activity.create(world["video"], "render_preview")
    main.activity.start(failed.job_id)
    main.activity.fail(failed.job_id, "vendor", "The vendor was down.")
    from app import errors_report
    errors_report.store(database, source="client", message="Boom", owner=MO)
    view = world["ada"].get(f"/admin/users/{SAM}").json()
    assert view["emails"] == ["sam.smith@example.com"] and view["kind"] == "google"
    assert [(m["member"], m["role"]) for m in view["workspace"]["members"]] == [(MO, "editor")]
    assert view["spend"]["all_time_usd"] == 0.25 and view["spend"]["today_usd"] == 0.25
    assert view["spend"]["by_vendor"] == {"elevenlabs": 0.25}
    kinds = {(j["kind"], j["status"]) for j in view["jobs"]}
    assert ("render_preview", "failed") in kinds and ("export", "queued") in kinds
    assert next(j for j in view["jobs"] if j["status"] == "failed")["error_text"] == "The vendor was down."
    assert [e["message"] for e in view["errors"]] == ["Boom"]
    assert view["suspended"] is None and view["credits"] is None
    assert world["ada"].get("/admin/users/google:nobody").status_code == 404


def test_grants_need_a_reason_and_are_audited(world):
    ada = world["ada"]
    assert ada.post(f"/admin/users/{SAM}/grant", json={"credits": 5}, headers=H).status_code == 422
    view = ada.post(f"/admin/users/{SAM}/grant", json={"credits": 7.5, "reason": "Beta thank you"}, headers=H).json()
    assert view["credits"]["granted"] == billing.TRIAL_CREDITS + 7.5
    assert any(g["kind"] == "admin" and g["credits"] == 7.5 and g["expires_at"] is None for g in view["credits"]["grants"])
    [row] = _trail(SAM)
    assert (row["actor"], row["action"], row["reason"], row["details"]["credits"]) == (ADA, "grant", "Beta thank you", 7.5)


def test_a_refund_goes_through_the_billing_path_or_reverses_credits(world):
    ada = world["ada"]
    inv = billing.buy_topup(database, SAM, billing.TOPUPS[0], "29")
    assert inv["test_mode"]
    out = ada.post(f"/admin/users/{SAM}/refund", json={"invoice_id": inv["id"], "reason": "Charged twice"}, headers=H)
    assert out.status_code == 200, out.text
    assert next(i for i in out.json()["invoices"] if i["id"] == inv["id"])["refunded"]
    again = ada.post(f"/admin/users/{SAM}/refund", json={"invoice_id": inv["id"], "reason": "Charged twice"}, headers=H)
    assert again.status_code == 422
    reversed_ = ada.post(f"/admin/users/{SAM}/refund", json={"credits": 2, "reason": "Credit given by mistake"}, headers=H)
    assert reversed_.status_code == 200
    assert any(g["kind"] == "refund" and g["credits"] == -2 for g in reversed_.json()["credits"]["grants"])
    assert ada.post(f"/admin/users/{SAM}/refund", json={"reason": "nothing named"}, headers=H).status_code == 422
    actions = [(r["action"], r["details"].get("invoice"), r["details"].get("credit_reversal")) for r in _trail(SAM)]
    assert actions == [("refund", None, 2), ("refund", inv["number"], None)]


def test_a_suspension_stops_the_owner_and_their_members_and_unsuspending_restores(world, monkeypatch):
    ada, sam, mo, video = world["ada"], world["sam"], world["mo"], world["video"]
    share = sam.post(f"/videos/{video}/shares", json={"scope": "video", "target": video, "days": 7}, headers=H)
    if share.status_code not in (200, 201):          # a share needs a project on this build: make one
        folder = sam.post("/projects", json={"name": "Sam's"}, headers=H).json()["project_id"]
        sam.patch(f"/videos/{video}", json={"project_id": folder}, headers=H)
        share = sam.post(f"/projects/{folder}/shares", json={"scope": "project", "days": 7}, headers=H)
    assert share.status_code in (200, 201), share.text
    token = share.json()["url"].split("#s/")[1]
    assert TestClient(app).get(f"/share/{token}").status_code == 200
    running = main.activity.create(video, "export")
    main.activity.start(running.job_id)
    mt = main.mint_media_token(SAM)["token"]

    assert ada.post(f"/admin/users/{SAM}/suspend", json={"reason": ""}, headers=H).status_code == 422
    assert ada.post(f"/admin/users/{ADA}/suspend", json={"reason": "test"}, headers=H).status_code == 422
    view = ada.post(f"/admin/users/{SAM}/suspend", json={"reason": "Abuse report 12"}, headers=H).json()
    assert view["suspended"]["reason"] == "Abuse report 12"

    for path in ("/videos", f"/videos/{video}", "/auth/me", "/billing", "/me/flags"):
        resp = sam.get(path)
        assert resp.status_code == 403 and resp.json() == {"detail": admin.SUSPENDED, "code": "suspended"}, path
    assert sam.post("/projects", json={"name": "x"}, headers=H).status_code == 403
    assert sam.post("/auth/logout", headers=H).status_code == 200
    # Mo, in Sam's workspace: refused, but may switch back to his own.
    resp = mo.get("/videos")
    assert resp.status_code == 403 and resp.json()["detail"] == admin.WORKSPACE_SUSPENDED
    assert mo.get("/workspace").status_code == 200
    # Links: the share page and signed media stop.
    shared = TestClient(app).get(f"/share/{token}")
    assert shared.status_code == 403 and shared.json()["detail"] == admin.SHARE_SUSPENDED
    with pytest.raises(Exception) as refused:
        main.media_owner(None, mt)
    assert getattr(refused.value, "status_code", None) == 403
    # Running work stopped; the next paid step refuses.
    assert main.activity.get(running.job_id).status == "cancelled"
    assert view["audit"][0]["details"]["jobs_stopped"] >= 1
    with pytest.raises(admin.AccountSuspended):
        main._ensure_spend(video)
    with pytest.raises(admin.AccountSuspended):
        main.budget.charge(video, 10)
    # Sign-in: the emailed link lands on the sign-in page with the sentence, no session.
    link = members_store.login_link(database, main.share_key, "sam.smith@example.com")
    back = TestClient(app).get("/auth/email/callback", params={"token": link}, follow_redirects=False)
    assert back.status_code == 302 and "#login?error=" in back.headers["location"]
    assert auth.SESSION_COOKIE not in back.cookies

    ada.post(f"/admin/users/{SAM}/unsuspend", json={"reason": "Report was mistaken"}, headers=H)
    assert sam.get("/videos").status_code == 200
    assert mo.get("/videos").status_code == 200
    assert TestClient(app).get(f"/share/{token}").status_code == 200
    assert main.media_owner(None, mt) == SAM
    main._ensure_spend(video)
    assert [r["action"] for r in _trail(SAM)] == ["unsuspend", "suspend"]


def test_a_suspended_password_account_cannot_sign_in(world, monkeypatch):
    from app.store import accounts as accounts_store
    acct, token = accounts_store.sign_up(database, "pat@shop.example", "a-long-password")
    accounts_store.use_token(database, "verify", token)
    admin.suspend(database, acct.owner, "spam", ADA)
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="accounts"))
    resp = TestClient(app).post("/auth/password/login", json={"email": "pat@shop.example", "password": "a-long-password"}, headers=H)
    assert resp.status_code == 403 and resp.json()["detail"] == admin.SUSPENDED
    assert auth.SESSION_COOKIE not in resp.cookies


def test_the_switch_and_flags_are_audited_and_the_trail_is_append_only(world):
    ada = world["ada"]
    ada.put("/admin/paid-pause", json={"paused": True, "reason": "Spend spike"}, headers=H)
    ada.put("/admin/paid-pause", json={"paused": False}, headers=H)
    ada.put("/admin/flags", json={"owner": SAM, "flag": "projects.batch", "enabled": False}, headers=H)
    trail = [e for e in ada.get("/admin/audit").json()["entries"] if e["id"] > _START[0]]
    assert [(e["action"], e["target"]) for e in trail[:3]] == [("flag", SAM), ("resume", None), ("pause", None)]
    assert trail[2]["reason"] == "Spend spike" and trail[0]["details"] == {"flag": "projects.batch", "enabled": False}
    with pytest.raises(Exception, match="append-only"):
        with database.tx() as c:
            c.execute("UPDATE admin_audit SET reason = 'edited'")
    with pytest.raises(Exception, match="append-only"):
        with database.tx() as c:
            c.execute("DELETE FROM admin_audit")


def test_an_admin_takes_a_share_link_down(world):
    sam, ada = world["sam"], world["ada"]
    folder = sam.post("/projects", json={"name": "Sam's"}, headers=H).json()["project_id"]
    made = sam.post(f"/projects/{folder}/shares", json={"scope": "project", "days": 7}, headers=H).json()
    token = made["url"].split("#s/")[1]
    gone = ada.post(f"/admin/shares/{token}/revoke", json={"reason": "Abuse report 3"}, headers=H)
    assert gone.status_code == 200 and gone.json()["state"] == "revoked"
    assert TestClient(app).get(f"/share/{token}").status_code == 410
    assert _trail(SAM)[0]["action"] == "share_revoke"


def test_the_migration_goes_down_only_when_empty(tmp_path):
    from app.store import migrate
    from app.store.migrations import m0036_admin_tools as m36
    conn = migrate.connect(str(tmp_path / "a.db"))
    migrate.up(conn)
    migrate.down_to(conn, 35)
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not {"admin_audit", "suspensions"} & have
    migrate.up(conn)
    conn.execute("INSERT INTO admin_audit (at, actor, action) VALUES ('t', 'a', 'grant')")
    with pytest.raises(RuntimeError, match="refusing"):
        m36.down(conn)
    conn.close()


def test_an_admin_entry_with_an_address_matches_a_proven_address(world, monkeypatch):
    """AVE_ADMIN_OWNERS may name the founder by address before their account exists."""
    from app.analytics_api import is_admin
    from app.store import accounts as accounts_store
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=(ADA, "Founder@Shop.example")))
    acct, token = accounts_store.sign_up(database, "founder@shop.example", "a-long-password")
    assert not is_admin(acct.owner)                                  # not until the address is verified
    accounts_store.use_token(database, "verify", token)
    assert is_admin(acct.owner) and is_admin(ADA)                     # owner-id entries work as before
    email_mod.remember_address(database, "google:fy", "FOUNDER@shop.example")
    assert is_admin("google:fy") and is_admin("email:founder@shop.example")
    assert not is_admin(SAM) and not is_admin("email:other@shop.example")
    session = TestClient(app)
    session.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": "fy", "email": "founder@shop.example", "name": None, "picture": None}, "s3cret"))
    assert session.get("/admin/users", params={"q": "sam"}).status_code == 200
    assert world["sam"].get("/admin/users", params={"q": "sam"}).status_code == 404
    from app.admin import admin_owner_ids
    assert set(admin_owner_ids(database, main.settings.admin_owners)) >= {ADA, acct.owner, "google:fy"}


def test_the_cli_suspends_and_audits(tmp_path, capsys):
    db_path = str(tmp_path / "c.db")
    from app.store.db import Database
    from app.notify import email as email_mod2
    email_mod2.remember_address(Database(db_path), "google:zed", "zed@example.com")
    assert admin.main(["find", "zed@", "--db", db_path]) == 0
    assert "google:zed" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        admin.main(["suspend", "google:zed", "--db", db_path])           # no reason
    admin.main(["suspend", "google:zed", "--reason", "Spend spike", "--db", db_path])
    db = Database(db_path)
    assert admin.suspension(db, "google:zed")["reason"] == "Spend spike"
    admin.main(["unsuspend", "google:zed", "--db", db_path])
    assert admin.suspension(db, "google:zed") is None
    assert [r["action"] for r in admin.recent_audit(db)] == ["unsuspend", "suspend"]
