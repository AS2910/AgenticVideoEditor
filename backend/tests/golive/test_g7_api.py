"""G7 through the API: the funnel from sign-in to first export fills from
the real routes; take acceptance and cost per exported minute come from the
events and the ledger; SIM-o and UTMOS only when measured; the browser may
post only client names, rate limited; the admin page is for admins with
`golive.g7` only."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import analytics_api
from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import generate
from tests.api.test_folders import upload_into
from tests.factories import export_now  # noqa: E402

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    main._funnel_started.clear()
    analytics_api.client_events.reset()
    yield
    flags.clear("golive.g7", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def names():
    with database.tx() as c:
        return [r[0] for r in c.execute("SELECT name FROM analytics_events ORDER BY id")]


def test_the_funnel_fills_from_sign_in_to_first_export(client, sample_video):
    client.get("/auth/me")
    client.get("/auth/me")                                               # once only
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    candidate = generate(project_id="p1")
    assert client.post("/videos/p1/edits", json={"candidate_id": candidate["candidate_id"]}).status_code == 200
    generate(project_id="p1", text="Another go")                       # voiced, not added
    out = export_now(client, "/videos/p1/export", json={"purpose": "export"})
    assert out.status_code == 200, out.text
    export_now(client, "/videos/p1/export", json={"purpose": "export"})         # a second export: first_export stays one
    seen = names()
    for step in ("signed_up", "first_sign_in", "video_uploaded", "take_voiced", "take_added", "first_export",
                 "edit.shipped", "video_exported"):
        assert step in seen, step
    assert seen.count("signed_up") == 1 and seen.count("first_export") == 1 and seen.count("video_exported") == 2

    page = client.get("/admin/analytics").json()
    funnel = {s["step"]: s["owners"] for s in page["funnel"]}
    assert funnel == {"signed_up": 1, "first_sign_in": 1, "video_uploaded": 1, "first_turn": 0, "take_voiced": 1,
                      "take_added": 1, "first_export": 1}
    assert page["take_acceptance"] == {"voiced": 2, "added": 1, "rate": 0.5}
    cost = page["cost_per_exported_minute"]
    spent = main.ledger.spent_usd_by_owner("local")
    assert cost["minutes"] > 0 and cost["per_minute"] == round(spent / cost["minutes"], 4)
    # The mock voice measures nothing: the vendor is listed, its scores are not made up.
    assert [(v["vendor"], v["sim_o"], v["utmos"], v["measured"]) for v in page["vendor_quality"]] == [(main.voice_label, None, None, False)]
    counts = {c["name"]: c["count"] for c in page["counts"]}
    assert counts["take_voiced"] == 2


def test_the_browser_posts_only_client_names_within_the_limit(client):
    assert client.post("/analytics/events", json={"name": "bell.opened", "props": {"unread": 2}}).status_code == 204
    assert client.post("/analytics/events", json={"name": "take_added"}).status_code == 422      # server-only
    assert client.post("/analytics/events", json={"name": "nope"}).status_code == 422
    with database.tx() as c:
        row = c.execute("SELECT owner, source FROM analytics_events WHERE name = 'bell.opened'").fetchone()
    assert (row["owner"], row["source"]) == ("local", "client")
    analytics_api.client_events.limit, was = 2, analytics_api.client_events.limit
    try:
        assert client.post("/analytics/events", json={"name": "bin.opened"}).status_code == 204
        assert client.post("/analytics/events", json={"name": "bin.opened"}).status_code == 429
    finally:
        analytics_api.client_events.limit = was


def test_admin_only_and_behind_the_flag(client, monkeypatch):
    assert client.get("/me/admin").json() == {"admin": True}
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=("someone-else",)))
    assert client.get("/admin/analytics").status_code == 404
    assert client.get("/me/admin").json() == {"admin": False}
    monkeypatch.undo()
    flags.set("golive.g7", "local", False)
    assert client.get("/admin/analytics").status_code == 404
    assert client.post("/analytics/events", json={"name": "bell.opened"}).status_code == 404
    assert client.get("/me/admin").json() == {"admin": False}


def test_a_share_page_open_is_counted_for_its_owner(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    made = client.post("/videos/p1/review-links", json={"name": "Priya", "days": 7})
    assert made.status_code == 201, made.text
    token = made.json()["url"].rsplit("/", 1)[-1]
    assert client.get(f"/share/{token}").status_code == 200
    with database.tx() as c:
        row = c.execute("SELECT owner FROM analytics_events WHERE name = 'review.page_opened'").fetchone()
    assert row["owner"] == "local"


def test_a_word_learned_from_the_transcript_is_counted(client):
    client.post("/projects", json={"name": "Diwali"})
    made = client.post("/projects/f1/rules?source=transcript", json={"kind": "pronounce", "data": {"term": "Bajicam", "say": "BAH-jee cam"}})
    assert made.status_code == 201, made.text
    client.post("/projects/f1/rules", json={"kind": "banned", "data": {"word": "cheap"}})
    seen = names()
    assert seen.count("words.learned_from_transcript") == 1 and seen.count("rule.added") == 2


def test_the_email_preview_is_for_admins_only_and_sends_nothing(client, monkeypatch):
    """Item 9: GET /admin/emails/preview lists the kinds; one kind is its subject, HTML and text."""
    from app.notify import email as email_mod, templates
    before = len(email_mod.outbox(database))
    kinds = client.get("/admin/emails/preview").json()["kinds"]
    assert [k["kind"] for k in kinds] == list(templates.KINDS)
    for k in templates.KINDS:
        one = client.get(f"/admin/emails/preview/{k}").json()
        assert one["subject"] and one["html"].startswith("<!doctype html>") and one["text"]
    invoice = client.get("/admin/emails/preview/invoice").json()
    assert main.settings.seller_name in invoice["text"]
    assert client.get("/admin/emails/preview/nope").status_code == 404
    assert len(email_mod.outbox(database)) == before                       # never sends
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=("someone-else",)))
    assert client.get("/admin/emails/preview").status_code == 404
    assert client.get("/admin/emails/preview/verify_email").status_code == 404
