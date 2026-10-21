"""G8: thumbs on takes and turns (stored, one per person and target, the
latest wins, shown on the admin page), the error-reporting hook (log
provider, a Sentry-shaped config that is not connected, the browser's
reports rate limited, a server error captured and raised on), Ask Voltage
finds the new Help articles, migration 0027 up and down."""

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import errors_report, feedback_api, help as help_mod
from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from app.store import feedback, migrate
from app.store.db import Database
from tests.api.test_folders import upload_into

ffmpeg_only = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    feedback_api.error_reports.reset()
    yield
    flags.clear("golive.g8", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def rows(table):
    with database.tx() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id")]


# ── the store ────────────────────────────────────────────────────────────────

def test_one_vote_per_person_and_target_the_latest_wins(tmp_path):
    db = Database(tmp_path / "t.db")
    feedback.give(db, "u", "p1", "take", "c3", "down", "  Too   fast ")
    feedback.give(db, "u", "p1", "take", "c3", "up")
    feedback.give(db, "v", "p1", "take", "c3", "down", "Wrong name")
    feedback.give(db, "u", "p1", "turn", "m12", "down", "Did not answer")
    assert feedback.for_video(db, "u", "p1") == {"take": {"c3": {"vote": "up", "reason": ""}}, "turn": {"m12": {"vote": "down", "reason": "Did not answer"}}}
    summary = feedback.summary(db)
    assert {t["target"]: (t["up"], t["down"]) for t in summary["totals"]} == {"take": (1, 1), "turn": (0, 1)}
    assert summary["recent"][0]["reason"] == "Did not answer"
    feedback.give(db, "u", "p1", "take", "c3", None)                     # taken back
    assert feedback.for_video(db, "u", "p1")["take"] == {}
    for bad in (("clip", "c3", "up"), ("take", "c 3; drop", "up"), ("take", "c3", "meh")):
        with pytest.raises(feedback.FeedbackError):
            feedback.give(db, "u", "p1", *bad)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM analytics_events WHERE name = 'feedback.given'").fetchone()[0] == 4


def test_reporters_stay_local_and_say_the_sentry_one_is_not_connected(tmp_path, caplog):
    db = Database(tmp_path / "t.db")
    assert isinstance(errors_report.reporter_for(None, db), errors_report.LogReporter)
    sentry = errors_report.reporter_for("https://key@o1.ingest.sentry.io/1", db)
    assert isinstance(sentry, errors_report.SentryReporter) and "not connected" in sentry.name
    try:
        raise ValueError("boom")
    except ValueError as exc:
        sentry.capture_exception(exc, {"where": "GET /x", "owner": "u"})
    sentry.capture_message("second", context={"source": "client"})
    assert "not connected" in caplog.text
    with db.tx() as c:
        got = [dict(r) for r in c.execute("SELECT source, message, location, owner FROM error_reports ORDER BY id")]
    assert got == [{"source": "server", "message": "ValueError: boom", "location": "GET /x", "owner": "u"},
                   {"source": "client", "message": "second", "location": "", "owner": None}]


def test_migration_0027_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"feedback", "error_reports"} <= tabs()
    migrate.down(conn, max(migrate.applied(conn)) - 26)   # back to 0026
    assert not ({"feedback", "error_reports"} & tabs()) and "analytics_events" in tabs()
    migrate.up(conn)
    assert {"feedback", "error_reports"} <= tabs()


def test_ask_voltage_finds_whats_new_and_the_thumbs_article():
    assert help_mod.search("what is new")[0]["slug"] == "whats-new"
    assert help_mod.search("how do I give feedback on a take")[0]["slug"] == "thumbs-up-or-down"


# ── through the API ──────────────────────────────────────────────────────────

@ffmpeg_only
def test_thumbs_through_the_api_and_on_the_admin_page(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    put = client.put("/videos/p1/feedback", json={"target": "take", "target_id": "c1", "vote": "down", "reason": "Too fast"})
    assert put.status_code == 200 and put.json()["vote"] == "down"
    client.put("/videos/p1/feedback", json={"target": "turn", "target_id": "m4", "vote": "up"})
    assert client.get("/videos/p1/feedback").json() == {"take": {"c1": {"vote": "down", "reason": "Too fast"}}, "turn": {"m4": {"vote": "up", "reason": ""}}}
    assert client.put("/videos/p1/feedback", json={"target": "clip", "target_id": "c1", "vote": "up"}).status_code == 422
    assert client.put("/videos/p9/feedback", json={"target": "take", "target_id": "c1", "vote": "up"}).status_code == 404
    page = client.get("/admin/analytics").json()
    assert {t["target"]: t["down"] for t in page["feedback"]["totals"]}["take"] == 1
    assert page["feedback"]["recent"][-1]["reason"] == "Too fast"
    flags.set("golive.g8", "local", False)
    assert client.get("/videos/p1/feedback").status_code == 404


def test_browser_errors_are_stored_and_limited(client):
    ok = client.post("/errors", json={"message": "TypeError: x is undefined", "stack": "at App", "where": "#v/p1", "kind": "boundary"})
    assert ok.status_code == 204
    got = rows("error_reports")[-1]
    assert (got["source"], got["message"], got["location"], got["owner"]) == ("client", "TypeError: x is undefined", "#v/p1", "local")
    feedback_api.error_reports.limit, was = 1, feedback_api.error_reports.limit
    try:
        feedback_api.error_reports.reset()
        assert client.post("/errors", json={"message": "a"}).status_code == 204
        assert client.post("/errors", json={"message": "b"}).status_code == 429
    finally:
        feedback_api.error_reports.limit = was
    flags.set("golive.g8", "local", False)
    assert client.post("/errors", json={"message": "c"}).status_code == 404


def test_a_server_error_is_captured_and_still_raised(client, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("the list broke")
    monkeypatch.setattr(main, "repo", replace_list(main.repo, broken))
    with pytest.raises(RuntimeError):
        client.get("/projects")
    got = rows("error_reports")[-1]
    assert got["source"] == "server" and got["message"] == "RuntimeError: the list broke" and got["location"] == "GET /projects"


def replace_list(repo_, broken):
    class Broken:
        def __getattr__(self, name):
            return broken if name == "list_projects" else getattr(repo_, name)
    return Broken()
