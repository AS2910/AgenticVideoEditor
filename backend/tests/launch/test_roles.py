"""Launch item 1: inside a workspace, the role decides. Ann owns the
workspace; Ed is an Editor; Rae is a Reviewer shared Ann's project "Ann's"
(with video p1 in it) but not the standalone video p2.

  - every write route answers 403 to Rae, except a comment on a shared video;
  - Rae reads only what was shared: the lists are filtered and anything else
    answers 404, as if it were not there;
  - every billing and members route answers 403 to Ed;
  - a job's notice goes to the member who started it; a spend alert to the
    owner and to that member.
"""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import auth
from app.api.main import app, database, flags, jobs, repo
from app.flags import KNOWN
from app.notify import email as email_mod
from app.notify import inbox
from app.workspace_api import OPEN_TO_ALL, REVIEWER_WRITES
from tests.launch.test_isolation import PUBLIC, _all_routes, _fill, _params, _request_kwargs

H = {"X-Requested-With": "voltage"}
ANN, ED, RAE = "google:ann", "google:ed", "google:rae"


def _client(sub: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": sub, "email": f"{sub}@example.com", "name": sub, "picture": None}, "s3cret"))
    return client


def _join(ann: TestClient, who: TestClient, email: str, role: str, **shares) -> None:
    out = ann.post("/workspace/invites", json={"email": email, "role": role, **shares}, headers=H)
    assert out.status_code == 201, out.text
    [mail] = email_mod.outbox(database, kind="workspace_invite", to=email)
    token = re.search(r"#invite/(\S+)", mail["body"]).group(1)
    assert mail["html"] and f"#invite/{token}" in mail["html"]          # item 9: the template, both parts
    joined = who.post(f"/invites/{token}/accept", headers=H)
    assert joined.status_code == 200, joined.text
    who.cookies.set("ave_workspace", joined.json()["workspace_id"])


@pytest.fixture(scope="module")
def team(sample_video):
    mp = pytest.MonkeyPatch()
    mp.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret"))
    repo.reset()
    jobs.reset()
    for who in (ANN, ED, RAE):
        for flag in KNOWN:
            if not flag.startswith("launch."):
                flags.set(flag, who, True)
    ann, ed, rae = _client("ann"), _client("ed"), _client("rae")
    ids = {}
    for name in ("ad.mp4", "b.mp4"):
        with open(sample_video, "rb") as handle:
            made = ann.post("/videos", files={"file": (name, handle, "video/mp4")}, data={"consent": "true"}, headers=H)
        assert made.status_code == 200, made.text
    ids.update(video="p1", spare="p2")
    ids["folder"] = ann.post("/projects", json={"name": "Ann's"}, headers=H).json()["project_id"]
    ann.patch("/videos/p1", json={"project_id": ids["folder"]}, headers=H)
    _join(ann, ed, "ed@example.com", "editor")
    _join(ann, rae, "rae@example.com", "reviewer", project_ids=[ids["folder"]])
    yield {"ann": ann, "ed": ed, "rae": rae, "ids": ids}
    mp.undo()
    for who in (ANN, ED, RAE):
        for flag in KNOWN:
            flags.clear(flag, who)


def _writes():
    seen = set()
    for route in _all_routes():
        if route.deprecated:
            continue
        for method in sorted(route.methods - {"GET", "HEAD", "OPTIONS"}):
            key = f"{method} {route.path}"
            probe = re.sub(r"{\w+(:\w+)?}", "x", route.path)
            if key in seen or key in PUBLIC or any(p.match(probe) for p in OPEN_TO_ALL):
                continue
            if any(p.match(probe) for p in REVIEWER_WRITES) or probe.startswith(("/billing/webhooks/", "/abuse-reports", "/errors", "/analytics/")):
                continue
            seen.add(key)
            yield pytest.param(method, route, id=key)


@pytest.mark.parametrize("method,route", list(_writes()))
def test_a_reviewer_cannot_write(team, method, route):
    path = _fill(route.path, team["ids"], route)
    resp = team["rae"].request(method, path, headers=H, params=_params(route, team["ids"]), **_request_kwargs(route))
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}: {resp.text[:200]}"


def _owner_only():
    for route in _all_routes():
        if route.path.startswith(("/billing", "/workspace/members", "/workspace/invites")) and not route.path.startswith("/billing/webhooks/"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield pytest.param(method, route, id=f"{method} {route.path}")


@pytest.mark.parametrize("method,route", list(_owner_only()))
def test_an_editor_cannot_touch_billing_or_members(team, method, route):
    path = _fill(route.path, team["ids"], route)
    resp = team["ed"].request(method, path, headers=H, params=_params(route, team["ids"]), **_request_kwargs(route))
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}: {resp.text[:200]}"


def test_a_reviewer_reads_only_what_was_shared(team):
    rae, ids = team["rae"], team["ids"]
    assert [v["video_id"] for v in rae.get("/videos").json()["videos"]] == [ids["video"]]
    assert [p["project_id"] for p in rae.get("/projects").json()["projects"]] == [ids["folder"]]
    assert rae.get(f"/videos/{ids['video']}").status_code == 200
    assert rae.get(f"/projects/{ids['folder']}").status_code == 200
    for path in (f"/videos/{ids['spare']}", f"/videos/{ids['spare']}/messages", "/usage", "/voices", "/templates",
                 "/search?q=ad", "/bin", "/pins", "/spend", "/voices/made", "/imports"):
        assert rae.get(path).status_code == 404, path
    # A comment on the shared video is the one write a Reviewer has.
    assert rae.post(f"/videos/{ids['video']}/comments", json={"text": "Lovely", "at_s": 0.5}, headers=H).status_code in (200, 201)
    assert rae.post(f"/videos/{ids['spare']}/comments", json={"text": "x", "at_s": 0.5}, headers=H).status_code == 404


def test_the_owner_changes_what_a_reviewer_sees(team):
    ann, rae, ids = team["ann"], team["rae"], team["ids"]
    page = ann.put(f"/workspace/members/{RAE}/shares", json={"video_ids": [ids["spare"]]}, headers=H)
    assert page.status_code == 200
    row = next(m for m in page.json()["members"] if m["member"] == RAE)
    assert row["shares"] == {"projects": [], "videos": [ids["spare"]]}
    assert [v["video_id"] for v in rae.get("/videos").json()["videos"]] == [ids["spare"]]
    assert rae.get(f"/videos/{ids['video']}").status_code == 404
    assert ann.put(f"/workspace/members/{RAE}/shares", json={"video_ids": ["p999"]}, headers=H).status_code == 404
    ann.put(f"/workspace/members/{RAE}/shares", json={"project_ids": [ids["folder"]]}, headers=H)


def test_an_editor_works_on_everything_in_the_workspace(team):
    ed, ids = team["ed"], team["ids"]
    assert {v["video_id"] for v in ed.get("/videos").json()["videos"]} == {ids["video"], ids["spare"]}
    assert ed.get("/usage").status_code == 200


def test_a_jobs_notice_reaches_the_member_who_started_it(team):
    from app.usage import current_actor
    token = current_actor.set(ED)
    try:
        job = main.activity.create("p1", "export", detail={"seconds": 600})
    finally:
        current_actor.reset(token)
    assert job.detail["started_by"] == ED
    main.activity.start(job.job_id)
    main.activity.fail(job.job_id, "unknown", "The vendor was down.")
    main._job_notice(main.activity.get(job.job_id))
    with database.tx() as c:
        to = [r[0] for r in c.execute("SELECT recipient FROM notifications WHERE kind = 'job_failed'")]
    assert ED in to and ANN not in to


def test_a_spend_alert_reaches_the_owner_and_the_member(team, monkeypatch):
    from app.usage import current_actor
    monkeypatch.setattr(main, "_spend_summary", lambda owner, **k: {
        "month": {"spent_usd": 9.0, "ceiling_usd": 10.0}, "video": None, "project": None})
    token = current_actor.set(ED)
    try:
        main._after_charge("p1", None)
    finally:
        current_actor.reset(token)
    with database.tx() as c:
        to = sorted(r[0] for r in c.execute("SELECT recipient FROM notifications WHERE kind = 'spend_alert'"))
    assert to == sorted([ANN, ED])
