"""C2 through the API: Send for review makes a reviewer link; the reviewer,
with no account, plays each version and reads what changed, comments at a
time, approves or asks for changes; the owner reads, replies to and
resolves comments; the owner's digest and the reviewer's new-version email
go through the email interface (the fake outbox)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from app.notify import digest, email as email_mod
from app.store import shares, stages
from app.timefmt import iso
from tests.api.test_endpoints import voiced
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.review", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def token_of(link):
    return link["url"].split("/#s/")[1]


def rendered_twice(client, monkeypatch):
    """p1 in project f1 with v1 (as shot) and a later final version (line 1 now says 30% off)."""
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video_path[0], "f1")
    assert client.post("/videos/p1/export", json={"purpose": "export"}).status_code == 200
    plan_id = voiced(client, monkeypatch)["plan"]["plan_id"]
    assert client.post(f"/videos/p1/plans/{plan_id}/approve", json={"items": ["i1"]}).status_code == 200
    assert client.post("/videos/p1/export", json={"purpose": "export"}).status_code == 200


sample_video_path: list = []


@pytest.fixture()
def two_versions(client, sample_video, monkeypatch):
    sample_video_path[:] = [sample_video]
    rendered_twice(client, monkeypatch)


ALLOWED_TOP = {"scope", "role", "name", "expires_at", "title", "files", "review"}
ALLOWED_FILE = {"file_id", "name", "kind", "size", "duration", "label", "video_id"}
ALLOWED_REVIEW = {"reviewer", "allow_download", "videos"}
ALLOWED_VIDEO = {"video_id", "title", "duration", "current_version", "versions", "comments", "answer", "read_only"}
ALLOWED_VERSION = {"version", "file_id", "duration", "created_at", "against", "changes"}
ALLOWED_COMMENT = {"comment_id", "author", "at_s", "version", "text", "status", "created_at", "replies"}


def test_send_for_review_shows_versions_with_what_changed_and_nothing_private(client, two_versions):
    made = client.post("/videos/p1/review-links", json={"name": "Priya", "email": "priya@client.example"})
    assert made.status_code == 201, made.text
    link = made.json()
    assert link["role"] == "reviewer" and link["data"]["allow_download"] is False
    assert stages.current(database, "p1") == "in_review"
    body = client.get(f"/share/{token_of(link)}").json()
    # Only the allowed keys, at every level: no voice ids, no costs, no project data, no paths.
    assert set(body) <= ALLOWED_TOP
    assert all(set(f) <= ALLOWED_FILE for f in body["files"])
    assert set(body["review"]) == ALLOWED_REVIEW
    [video] = body["review"]["videos"]
    assert set(video) == ALLOWED_VIDEO
    assert all(set(v) == ALLOWED_VERSION for v in video["versions"])
    text = repr(body)
    for private in ("voice", "usd", "cost", "brief", "sha256", "path", "owner", "workspace", "mock"):
        assert private not in text.lower(), private
    # v1 as shot; the turn's preview took a number, so the edited final is the next one up.
    v2, v1 = video["versions"]
    assert v1["version"] == 1 and v2["version"] > 1 and video["current_version"] == v2["version"]
    assert v1["against"] == "as shot" and v1["changes"] == []
    assert v2["against"] == "v1" and v2["changes"] == ['0:00 now says "Get 30% off today only."']
    # Every version plays; download is refused while the link does not allow it.
    played = client.get(f"/share/{token_of(link)}/files/{v1['file_id']}")
    assert played.status_code == 200 and played.headers["content-disposition"].startswith("inline")
    refused = client.get(f"/share/{token_of(link)}/files/{v2['file_id']}?download=true")
    assert refused.status_code == 403 and refused.json()["detail"] == "Downloading is turned off for this link."
    allowed = client.post("/videos/p1/review-links", json={"allow_download": True}).json()
    assert client.get(f"/share/{token_of(allowed)}/files/{v2['file_id']}?download=true").status_code == 200


def test_a_comment_lands_at_its_timecode_and_the_owner_replies_and_resolves(client, two_versions):
    link = client.post("/videos/p1/review-links", json={"name": "Priya"}).json()
    said = client.post(f"/share/{token_of(link)}/comments", json={"video_id": "p1", "at_s": 1.234, "version": 1, "text": "  Logo bigger here  "})
    assert said.status_code == 201, said.text
    comment = said.json()
    assert set(comment) == ALLOWED_COMMENT
    assert (comment["at_s"], comment["version"], comment["text"], comment["author"]) == (1.23, 1, "Logo bigger here", "Priya")
    mine = client.get("/videos/p1/comments").json()
    assert mine["open"] == 1 and mine["comments"][0]["at_s"] == 1.23 and mine["comments"][0]["link_name"] == "Priya"
    assert client.get("/projects/f1/videos").json()["videos"][0]["open_comments"] == 1
    cid = comment["comment_id"]
    replied = client.post(f"/videos/p1/comments/{cid}/replies", json={"text": "On it."})
    assert replied.status_code == 200 and replied.json()["replies"][0]["text"] == "On it."
    # The reviewer sees the reply, unnamed.
    seen = client.get(f"/share/{token_of(link)}").json()["review"]["videos"][0]["comments"][0]
    assert seen["replies"] == [{"author": "The editor", "text": "On it.", "at": seen["replies"][0]["at"]}]
    assert client.post(f"/videos/p1/comments/{cid}/resolve", json={}).json()["status"] == "resolved"
    assert client.get("/projects/f1/videos").json()["videos"][0]["open_comments"] == 0
    verbs = [e for e in client.get("/videos/p1/events/log").json()["events"] if e["verb"].startswith("review.")]
    assert [e["verb"] for e in verbs] == ["review.resolved", "review.replied", "review.commented"]
    assert (verbs[-1]["actor_kind"], verbs[-1]["actor_name"]) == ("reviewer", "Priya")
    # Out of the video's length, an unknown version, or empty: refused with a sentence.
    for bad in ({"at_s": 99, "version": 1, "text": "x"}, {"at_s": 1, "version": 7, "text": "x"}, {"at_s": 1, "text": " "}):
        assert client.post(f"/share/{token_of(link)}/comments", json={"video_id": "p1", **bad}).status_code == 422


def test_approving_through_the_link_sets_the_stage_and_logs_the_reviewers_name(client, two_versions):
    link = client.post("/videos/p1/review-links", json={"name": "Priya"}).json()
    done = client.post(f"/share/{token_of(link)}/approve", json={"video_id": "p1", "version": 1, "note": "Lovely."})
    assert done.status_code == 200, done.text
    assert done.json()["answer"]["answer"] == "approved" and done.json()["answer"]["by"] == "Priya"
    assert stages.current(database, "p1") == "approved"
    move = next(e for e in client.get("/videos/p1/events/log").json()["events"] if e["verb"] == "stage.moved")
    assert (move["actor_kind"], move["actor_name"], move["payload"]["why"]) == ("reviewer", "Priya", "Approved v1 by review link.")
    asked = client.post(f"/share/{token_of(link)}/changes", json={"video_id": "p1", "note": "Shorter please"})
    assert asked.status_code == 200 and stages.current(database, "p1") == "changes_asked"
    assert client.get(f"/share/{token_of(link)}").json()["review"]["videos"][0]["answer"]["answer"] == "changes_asked"


def test_an_unnamed_link_takes_the_reviewers_own_name(client, two_versions):
    link = client.post("/videos/p1/review-links", json={}).json()
    client.post(f"/share/{token_of(link)}/approve", json={"video_id": "p1", "name": "Ravi"})
    move = next(e for e in client.get("/videos/p1/events/log").json()["events"] if e["verb"] == "stage.moved")
    assert move["actor_name"] == "Ravi"


def test_a_revoked_or_expired_review_link_is_refused(client, two_versions, monkeypatch):
    link = client.post("/videos/p1/review-links", json={"name": "Priya"}).json()
    token = token_of(link)
    assert [l["share_id"] for l in client.get("/videos/p1/review-links").json()["links"]] == [link["share_id"]]
    monkeypatch.setattr(shares, "now_iso", lambda: "2999-01-01T00:00:00.000Z")
    expired = client.get(f"/share/{token}")
    assert expired.status_code == 410 and expired.json()["detail"] == "This link has expired. Ask the person who shared it for a new one."
    monkeypatch.undo()
    assert client.delete(f"/videos/p1/review-links/{link['share_id']}").json()["state"] == "revoked"
    for call in (lambda: client.get(f"/share/{token}"),
                 lambda: client.post(f"/share/{token}/comments", json={"video_id": "p1", "at_s": 1, "text": "hi"}),
                 lambda: client.post(f"/share/{token}/approve", json={"video_id": "p1"})):
        refused = call()
        assert refused.status_code == 410 and refused.headers["x-share-refused"] == "revoked"
    assert stages.current(database, "p1") == "in_review"


def test_an_archived_projects_review_link_is_watch_only(client, two_versions):
    """D4: archiving the project closes comments and answers through its
    review links with one sentence; watching every version still works."""
    link = client.post("/videos/p1/review-links", json={"name": "Priya"}).json()
    token = token_of(link)
    assert client.get(f"/share/{token}").json()["review"]["videos"][0]["read_only"] is None
    assert client.post("/projects/f1/archive").status_code == 200
    [video] = client.get(f"/share/{token}").json()["review"]["videos"]
    assert video["read_only"] == main.REVIEW_ARCHIVED
    assert "archived" in video["read_only"] and "watch" in video["read_only"]
    for path, body in (("comments", {"video_id": "p1", "at_s": 1, "text": "hi"}),
                       ("approve", {"video_id": "p1"}), ("changes", {"video_id": "p1", "note": "x"})):
        refused = client.post(f"/share/{token}/{path}", json=body)
        assert refused.status_code == 423 and refused.json()["detail"] == main.REVIEW_ARCHIVED
    assert client.get(f"/share/{token}/files/{video['versions'][0]['file_id']}").status_code == 200
    assert stages.current(database, "p1") == "in_review" and client.get("/videos/p1/comments").json()["comments"] == []
    # Unarchived: open again.
    assert client.delete("/projects/f1/archive").status_code == 200
    assert client.post(f"/share/{token}/comments", json={"video_id": "p1", "at_s": 1, "text": "hi"}).status_code == 201


def test_a_viewer_link_cannot_comment_or_answer(client, two_versions):
    viewer = client.post("/projects/f1/shares", json={"scope": "video", "target": "p1"}).json()
    assert "review" not in client.get(f"/share/{token_of(viewer)}").json()
    assert client.post(f"/share/{token_of(viewer)}/comments", json={"video_id": "p1", "at_s": 1, "text": "hi"}).status_code == 403


def test_a_project_link_asks_about_the_chosen_videos_only(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video, "f1", name="a.mp4")
    upload_into(client, sample_video, "f1", name="b.mp4")
    made = client.post("/projects/f1/shares", json={"scope": "project", "role": "reviewer", "videos": ["p2"], "name": "Priya"})
    assert made.status_code == 201, made.text
    assert (stages.current(database, "p1"), stages.current(database, "p2")) == ("draft", "in_review")
    body = client.get(f"/share/{token_of(made.json())}").json()
    assert [v["video_id"] for v in body["review"]["videos"]] == ["p2"] and body["review"]["videos"][0]["versions"] == []
    assert client.post(f"/share/{token_of(made.json())}/comments", json={"video_id": "p1", "at_s": 0, "text": "x"}).status_code == 404
    assert client.post("/projects/f1/shares", json={"scope": "project", "role": "reviewer", "videos": ["p9"]}).status_code == 404
    assert client.post("/projects/f1/shares", json={"scope": "project", "role": "reviewer", "email": "nope"}).status_code == 422


def test_the_flag_off_hides_the_owners_review_routes(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video, "f1")
    flags.set("projects.review", "local", False)
    assert client.post("/videos/p1/review-links", json={}).status_code == 404
    assert client.get("/videos/p1/comments").status_code == 404


def test_the_owners_digest_batches_ten_minutes_of_news_into_one_email(client, two_versions, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(main, "settings", replace(main.settings, notify_owner_email="owner@agency.example"))
    link = client.post("/videos/p1/review-links", json={"name": "Priya"}).json()
    token = token_of(link)
    client.post(f"/share/{token}/comments", json={"video_id": "p1", "at_s": 1.0, "version": 1, "text": "Logo bigger"})
    client.post(f"/share/{token}/approve", json={"video_id": "p1", "version": 1})
    queued = digest.pending(database)
    assert [i["kind"] for i in queued] == ["comment", "approved"]
    from datetime import datetime, timezone
    first = datetime.fromisoformat(queued[0]["at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    assert main.flush_review_digests(first + timedelta(minutes=9)) == []          # not 10 minutes yet
    [sent] = main.flush_review_digests(first + timedelta(minutes=10, seconds=1))
    assert sent.to == "owner@agency.example" and sent.subject == "2 updates from your reviewers"
    assert 'Priya commented on ad.mp4 at 0:01 (v1): "Logo bigger"' in sent.body and "Priya approved ad.mp4 v1." in sent.body
    assert "/#p/f1" in sent.body
    assert sent.html and "Open the project" in sent.html and "/#notifications" in sent.body          # item 9: the digest template
    assert main.flush_review_digests(first + timedelta(minutes=30)) == []         # nothing new
    assert [e["kind"] for e in email_mod.outbox(database, kind="digest")] == ["digest"]


def test_a_reviewer_with_an_email_hears_about_a_new_version_once(client, two_versions, monkeypatch):
    link = client.post("/videos/p1/review-links", json={"name": "Priya", "email": "priya@client.example"}).json()
    [invite] = email_mod.outbox(database, kind="review_invite")
    assert invite["to_addr"] == "priya@client.example" and token_of(link) in invite["body"]
    assert invite["subject"].startswith("Please review") and token_of(link) in invite["html"]          # item 9
    assert email_mod.outbox(database, kind="version_ready") == []                 # the version it was sent on
    plan_id = voiced(client, monkeypatch, text="Get 40% off today only.")["plan"]["plan_id"]
    client.post(f"/videos/p1/plans/{plan_id}/approve", json={"items": ["i1"]})
    client.post("/videos/p1/export", json={"purpose": "export"})
    client.post("/videos/p1/export", json={"purpose": "export"})                  # the same version again
    [told] = email_mod.outbox(database, kind="version_ready")
    newest = client.get(f"/share/{token_of(link)}").json()["review"]["videos"][0]["current_version"]
    assert told["to_addr"] == "priya@client.example" and told["subject"] == f"v{newest} of ad.mp4 is ready to review"
    assert told["html"] and "Hi Priya," in told["body"]          # item 9: the template
