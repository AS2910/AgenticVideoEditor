"""G2 through the API, with sign-in on and test owners: the owner invites by
email (the fake outbox), the invitee accepts the signed link and works in
the owner's workspace; Editors can do everything but members and billing,
Reviewers read and comment; a member's spend limit holds in the spend
guard; email sign-in by a one-use link. With sign-in off the local owner
is the Owner."""
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import auth
from app.api.main import app, database, flags, jobs, ledger, repo
from app.notify import email as email_mod
from app.usage import MemberLimitReached

H = {"X-Requested-With": "voltage"}
A, B, C = "google:a", "google:b", "google:c"


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    repo.reset()
    jobs.reset()
    yield
    for who in (A, B, C, "local"):
        for f in ("golive.g2", "projects.review"):
            flags.clear(f, who)


@pytest.fixture()
def sign_in_on(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret",
                                                  public_url="http://localhost:5173"))
    for who in (A, B, C):
        flags.set("golive.g2", who, True)
        flags.set("projects.review", who, True)


def as_user(sub: str, email: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign({"sub": sub, "email": email, "name": None, "picture": None}, "s3cret"))
    return client


def invite_and_join(owner: TestClient, member: TestClient, email: str, role: str, limit=None, videos=()) -> str:
    out = owner.post("/workspace/invites", json={"email": email, "role": role, "spend_limit_usd": limit,
                                                 "video_ids": list(videos)}, headers=H)
    assert out.status_code == 201, out.text
    [mail] = email_mod.outbox(database, kind="workspace_invite", to=email)
    token = re.search(r"#invite/(\S+)", mail["body"]).group(1)
    assert out.json()["invite"]["link"].endswith(token)
    seen = TestClient(app).get(f"/invites/{token}").json()          # public: no account needed to read it
    assert seen["role"] == role and seen["email"] == email
    joined = member.post(f"/invites/{token}/accept", headers=H)
    assert joined.status_code == 200, joined.text
    member.cookies.set("ave_workspace", joined.json()["workspace_id"])
    return token


def test_an_editor_works_in_the_owners_workspace_but_not_on_its_members(sign_in_on):
    a, b = as_user("a", "a@x.io"), as_user("b", "b@x.io")
    a.post("/projects", json={"name": "Diwali"}, headers=H)
    token = invite_and_join(a, b, "b@x.io", "editor")
    assert b.post(f"/invites/{token}/accept", headers=H).status_code == 410        # one use
    assert [p["name"] for p in b.get("/projects").json()["projects"]] == ["Diwali"]
    made = b.post("/projects", json={"name": "From B"}, headers=H)
    assert made.status_code == 201 and repo.get_project(made.json()["project_id"]).owner == A   # the work is the owner's
    assert b.get("/workspace").json()["you"] == {"user": B, "role": "editor"}
    refused = b.get("/workspace/members")
    assert refused.status_code == 403 and refused.json()["detail"] == "Only the workspace owner can manage members and billing."
    assert b.post("/workspace/invites", json={"email": "z@x.io", "role": "editor"}, headers=H).status_code == 403
    page = a.get("/workspace/members").json()
    assert [(r["member"], r["role"]) for r in page["members"]] == [(B, "editor")] and page["owner"]["role"] == "owner"
    # Back in their own workspace, B sees their own (empty) work.
    b.post("/workspace/switch", json={"workspace_id": None}, headers=H)
    b.cookies.delete("ave_workspace")
    assert b.get("/projects").json()["projects"] == []


def test_a_reviewer_reads_and_comments_and_nothing_else(sign_in_on, sample_video):
    a, c = as_user("a", "a@x.io"), as_user("c", "c@x.io")
    with open(sample_video, "rb") as handle:
        vid = a.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H).json()["video_id"]
    invite_and_join(a, c, "c@x.io", "reviewer", videos=[vid])         # launch item 1: a Reviewer sees what was shared
    assert c.get(f"/videos/{vid}").status_code == 200
    no = c.post("/projects", json={"name": "Nope"}, headers=H)
    assert no.status_code == 403 and "As a Reviewer you can watch and comment" in no.json()["detail"]
    assert c.delete(f"/videos/{vid}", headers=H).status_code == 403
    said = c.post(f"/videos/{vid}/comments", json={"at_s": 1.0, "text": "Louder here."}, headers=H)
    assert said.status_code == 201, said.text
    assert said.json()["author_name"] == "c@x.io" and said.json()["author_kind"] == "member"
    assert [x["text"] for x in a.get(f"/videos/{vid}/comments").json()["comments"]] == ["Louder here."]


def test_the_owner_changes_roles_and_limits_and_removes(sign_in_on):
    a, b = as_user("a", "a@x.io"), as_user("b", "b@x.io")
    invite_and_join(a, b, "b@x.io", "editor", 20)
    page = a.patch(f"/workspace/members/{B}", json={"role": "reviewer", "spend_limit_usd": 5}, headers=H).json()
    assert (page["members"][0]["role"], page["members"][0]["spend_limit_usd"]) == ("reviewer", 5)
    assert a.patch(f"/workspace/members/{B}", json={"spend_limit_usd": None}, headers=H).json()["members"][0]["spend_limit_usd"] is None
    assert a.patch(f"/workspace/members/{B}", json={"role": "owner"}, headers=H).status_code == 422
    assert a.delete(f"/workspace/members/{B}", headers=H).json()["members"] == []
    assert b.get("/workspace").json()["you"]["role"] == "owner"          # back in their own workspace
    waiting = a.post("/workspace/invites", json={"email": "q@x.io", "role": "reviewer"}, headers=H).json()["invite"]
    assert a.delete(f"/workspace/invites/{waiting['id']}", headers=H).json()["invites"] == []


def test_a_members_spend_counts_against_their_limit_in_the_spend_guard(sign_in_on, sample_video):
    a, b = as_user("a", "a@x.io"), as_user("b", "b@x.io")
    invite_and_join(a, b, "b@x.io", "editor", 0.25)
    wid = a.get("/workspace").json()["workspace"]["workspace_id"]
    with open(sample_video, "rb") as handle:
        vid = a.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H).json()["video_id"]
    acting = main.Acting(B, A, "editor", wid)
    t1, t2 = main.acting.set(acting), main.current_actor.set(B)
    try:
        main._ensure_spend(vid)                                           # nothing spent yet
        ledger.record(vid, "anthropic", "turn", 100, "tokens", 0.30)
        with pytest.raises(MemberLimitReached):
            main._ensure_spend(vid)
    finally:
        main.acting.reset(t1)
        main.current_actor.reset(t2)
    main._ensure_spend(vid)                                               # the owner has no member limit
    assert a.get("/workspace/members").json()["members"][0]["spent_usd"] == pytest.approx(0.30)


def test_email_sign_in_by_a_one_use_link(sign_in_on, monkeypatch):
    flags.set("golive.g2", "local", True)
    client = TestClient(app)
    assert client.get("/auth/email").json() == {"available": True}
    assert client.post("/auth/email", json={"email": "nope"}).status_code == 403     # item 5: the CSRF header, like every write
    assert client.post("/auth/email", json={"email": "nope"}, headers=H).status_code == 422
    assert client.post("/auth/email", json={"email": "New@X.io"}, headers=H).json() == {"sent": True, "email": "new@x.io"}
    [mail] = email_mod.outbox(database, kind="sign_in")
    link = re.search(r"callback\?token=(\S+)", mail["body"]).group(1)
    assert mail["subject"] == "Your Voltage sign-in link" and link in mail["html"]          # item 9: the template
    back = client.get(f"/auth/email/callback?token={link}", follow_redirects=False)
    assert back.status_code == 302 and back.headers["location"] == "http://localhost:5173/"
    assert client.get("/auth/me").json()["user"]["email"] == "new@x.io"
    client.post("/projects", json={"name": "Mine"}, headers=H)
    assert repo.list_projects("email:new@x.io")[0].name == "Mine"
    assert TestClient(app).get(f"/auth/email/callback?token={link}", follow_redirects=False).status_code == 410
    # An address a Google sign-in remembered reaches that same account.
    email_mod.remember_address(database, A, "a@x.io")
    client2 = TestClient(app)
    client2.post("/auth/email", json={"email": "a@x.io"}, headers=H)
    link2 = re.search(r"callback\?token=(\S+)", email_mod.outbox(database, kind="sign_in", to="a@x.io")[0]["body"]).group(1)
    client2.get(f"/auth/email/callback?token={link2}", follow_redirects=False)
    client2.post("/projects", json={"name": "A again"}, headers=H)
    assert [p.name for p in repo.list_projects(A)] == ["A again"]


def test_with_sign_in_off_the_local_owner_is_the_owner():
    client = TestClient(app)
    assert client.get("/workspace").json()["you"] == {"user": "local", "role": "owner"}
    out = client.post("/workspace/invites", json={"email": "ed@x.io", "role": "editor"})
    assert out.status_code == 201 and out.json()["sign_in"] is False
    token = out.json()["invite"]["link"].split("#invite/")[1]
    refused = client.post(f"/invites/{token}/accept")
    assert refused.status_code == 409 and "Sign-in is off" in refused.json()["detail"]
    assert client.get("/auth/email").json() == {"available": False}
    flags.set("golive.g2", "local", False)
    assert client.get("/workspace/members").status_code == 404


def test_work_started_by_a_member_carries_who_into_its_charges():
    """A turn runs on the job pool; its charges still name who started it."""
    import time
    token = main.current_actor.set(B)
    try:
        job = main.jobs.create("turn", "p1")
        main.runner.submit(job, lambda report: {"who": main.current_actor.get()})
    finally:
        main.current_actor.reset(token)
    for _ in range(100):
        if main.jobs.get(job.job_id).done:
            break
        time.sleep(0.05)
    assert main.jobs.get(job.job_id).result == {"who": B}


@pytest.mark.parametrize("role", ["editor", "reviewer"])
def test_a_member_deleting_their_account_deletes_only_their_own(sign_in_on, role):
    """Rehearsal P0: an Editor's DELETE /account, sent while working in the owner's
    workspace, deleted the owner's account and every video in it."""
    a, b = as_user("a", "a@x.io"), as_user("b", "b@x.io")
    made = a.post("/projects", json={"name": "Diwali"}, headers=H).json()["project_id"]
    invite_and_join(a, b, "b@x.io", role)
    assert b.delete("/account", headers=H).status_code == 204          # a Reviewer may delete their own too
    assert repo.get_project(made) is not None                          # the owner's work is all there
    assert [p["name"] for p in a.get("/projects").json()["projects"]] == ["Diwali"]
    assert a.get("/workspace/members").json()["members"] == []         # and B left the workspace
