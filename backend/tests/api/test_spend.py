"""Spend scopes: turn → video → project → month. One summary (`GET /spend`)
names every scope and the binding one; the ledger keeps each row's video,
project (at the time) and turn; Usage groups by project with the videos
nested; the agent reads the same numbers in project_state."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg
from tests.api.test_endpoints import await_job, send, turn, upload
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def folder(client, name="Ashish Testing", ceiling=None):
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    if ceiling is not None:
        client.patch(f"/projects/{resp.json()['project_id']}", json={"ceiling_usd": ceiling})
    return resp.json()["project_id"]


def month():
    from app.usage import month_name
    return month_name()


# ── the summary ──────────────────────────────────────────────────────────────

def test_the_binding_scope_is_the_one_with_the_least_headroom(client, sample_video, monkeypatch):
    import app.api.main as main
    from dataclasses import replace
    fid = folder(client)
    upload_into(client, sample_video, fid)
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.6)

    spend = client.get("/spend", params={"video": "p1"}).json()
    assert set(spend) == {"video", "project", "month", "binding"}          # no turn yet
    assert spend["video"] == {"spent_usd": 0.6, "ceiling_usd": 2.0, "label": "This video"}
    assert spend["project"] == {"spent_usd": 0.6, "ceiling_usd": None, "label": "Project Ashish Testing"}
    assert spend["month"] == {"spent_usd": 0.6, "ceiling_usd": main.settings.user_budget_usd, "label": month()}
    assert spend["binding"] == "video"                                    # 1.40 left, the month has more

    client.patch(f"/projects/{fid}", json={"ceiling_usd": 1.0})
    assert client.get("/spend", params={"video": "p1"}).json()["binding"] == "project"   # 0.40 left

    monkeypatch.setattr(main, "settings", replace(main.settings, user_budget_usd=0.7))
    assert client.get("/spend", params={"video": "p1"}).json()["binding"] == "month"     # 0.10 left

    # A tie goes to the narrower scope.
    assert main._binding({"video": {"spent_usd": 1, "ceiling_usd": 2, "label": ""},
                          "project": {"spent_usd": 9, "ceiling_usd": 10, "label": ""},
                          "month": {"spent_usd": 99, "ceiling_usd": 100, "label": ""}}) == "video"
    # The turn's cap never binds: it starts again with every turn.
    assert main._binding({"turn": {"spent_usd": 0.5, "ceiling_usd": 0.5, "label": ""},
                          "video": {"spent_usd": 0, "ceiling_usd": 2, "label": ""}}) == "video"


def test_a_standalone_video_has_no_project_line(client, sample_video):
    upload(client, sample_video)
    spend = client.get("/spend", params={"video": "p1"}).json()
    assert "project" not in spend and set(spend) == {"video", "month", "binding"}
    assert set(client.get("/spend").json()) == {"month", "binding"}
    assert client.get("/spend", params={"video": "p9"}).status_code == 404


def test_a_project_summary_has_the_project_and_the_month(client, sample_video):
    fid = folder(client, ceiling=10)
    spend = client.get("/spend", params={"project": fid}).json()
    assert spend["project"] == {"spent_usd": 0.0, "ceiling_usd": 10.0, "label": "Project Ashish Testing"}
    assert set(spend) == {"project", "month", "binding"}
    assert client.get("/spend", params={"project": "f9"}).status_code == 404


# ── the ledger: video, project at the time, turn ──────────────────────────────

def test_a_turn_tags_its_rows_and_the_result_carries_the_summary(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    fid = folder(client)
    upload_into(client, sample_video, fid)
    main.ledger.record("p1", "openai", "transcription", 1, "minutes", 0.01)   # outside any turn

    result = turn(client, monkeypatch, [reply(said("Nothing to change."))], text="hi")
    [job] = [j for j in jobs.all() if j.kind == "turn"]
    with main.database.tx() as c:
        rows = [(r["turn_id"], r["folder_id"]) for r in c.execute("SELECT turn_id, folder_id FROM usage WHERE project_id = 'p1' ORDER BY id")]
    assert rows[0] == (None, fid) and rows[1:] and all(r == (job.job_id, fid) for r in rows[1:])

    spend = result["spend"]
    assert spend["turn"]["label"] == "This turn" and spend["turn"]["spent_usd"] > 0
    assert spend["turn"]["ceiling_usd"] == main._settings("p1")["turn_usd"]
    assert spend["video"]["spent_usd"] == pytest.approx(spend["turn"]["spent_usd"] + 0.01, abs=1e-4)
    assert spend["project"]["spent_usd"] == spend["video"]["spent_usd"]
    assert client.get("/spend", params={"video": "p1"}).json()["turn"] == spend["turn"]


def test_moving_a_video_keeps_its_historical_spend_under_its_old_project(client, sample_video):
    import app.api.main as main
    old, new = folder(client, "Spring sale"), folder(client, "Autumn")
    upload_into(client, sample_video, old)
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.25)
    assert client.patch("/videos/p1", json={"project_id": new}).status_code == 200
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.5)

    assert client.get("/spend", params={"project": old}).json()["project"]["spent_usd"] == 0.25
    assert client.get("/spend", params={"project": new}).json()["project"]["spent_usd"] == 0.5
    video = client.get("/spend", params={"video": "p1"}).json()
    assert video["video"]["spent_usd"] == 0.75 and video["project"]["label"] == "Project Autumn"

    usage = client.get("/usage").json()
    groups = {g["name"]: g for g in usage["groups"]}
    assert [(v["video_id"], v["spent_usd"], v["here"]) for v in groups["Spring sale"]["videos"]] == [("p1", 0.25, False)]
    assert [(v["video_id"], v["spent_usd"], v["here"]) for v in groups["Autumn"]["videos"]] == [("p1", 0.5, True)]
    assert groups["No project"]["videos"] == []
    scoped = client.get("/usage", params={"scope": old}).json()["totals"]
    assert (scoped["label"], scoped["spent_usd"]) == ("Project Spring sale", 0.25)


def test_project_level_charges_have_no_video_and_count_in_the_project_and_the_month(client, sample_video):
    import app.api.main as main
    fid = folder(client, ceiling=5)
    upload(client, sample_video, name="alone.mp4")
    main.ledger.record_project_level(fid, "elevenlabs", "voice design", 300, "characters", 0.09)
    main.ledger.record("p1", "openai", "transcription", 1, "minutes", 0.01)
    with main.database.tx() as c:
        row = c.execute("SELECT project_id, folder_id FROM usage WHERE what = 'voice design'").fetchone()
    assert (row["project_id"], row["folder_id"]) == ("", fid)

    usage = client.get("/usage").json()
    project, alone = usage["groups"]
    assert (project["name"], project["project_level_usd"], project["videos"], project["spent_usd"]) == ("Ashish Testing", 0.09, [], 0.09)
    assert (alone["project_id"], alone["name"], alone["project_level_usd"]) == (None, "No project", None)
    assert [(v["filename"], v["spent_usd"]) for v in alone["videos"]] == [("alone.mp4", 0.01)]
    assert client.get("/spend", params={"project": fid}).json()["project"]["spent_usd"] == 0.09
    assert client.get("/spend").json()["month"]["spent_usd"] == 0.1

    totals = usage["totals"]
    assert (totals["scope"], totals["label"], totals["spent_usd"], totals["ceiling_usd"]) == ("all", month(), 0.1, main.settings.user_budget_usd)
    none = client.get("/usage", params={"scope": "none"}).json()["totals"]
    assert (none["label"], none["spent_usd"], none["ceiling_usd"]) == ("Standalone videos", 0.01, None)
    one = client.get("/usage", params={"scope": "v:p1"}).json()["totals"]
    assert (one["label"], one["spent_usd"], one["ceiling_usd"]) == ("alone.mp4", 0.01, 2.0)
    assert {v["vendor"]: v["usd"] for v in one["by_vendor"]}["openai"] == 0.01


# ── the refusal names the scope, and the agent reads the same numbers ─────────

def test_the_refusal_names_the_project_and_what_to_do(client, sample_video, monkeypatch):
    import app.api.main as main
    fid = folder(client, ceiling=10)
    upload_into(client, sample_video, fid)
    main.ledger.record("p1", "anthropic", "agent", 1, "tokens", 1.0)
    main.ledger.record_project_level(fid, "elevenlabs", "voice design", 1, "characters", 9.0)
    from tests.api.test_endpoints import _agent_on
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [])
    result = send(client, "make it 30% off")
    assert result["reply"] == ("Ashish Testing has reached its $10 project ceiling. "
                               "Raise it on the project page, or move the video out.")
    assert result["ceiling"] == "project" and result["spend"]["binding"] == "project"


def test_project_state_carries_the_spend_line(client, sample_video, monkeypatch):
    import app.api.main as main
    from app.agent.tools import spend_state
    fid = folder(client)
    upload_into(client, sample_video, fid)
    upload(client, sample_video, name="alone.mp4")
    main.ledger.record("p1", "elevenlabs", "speech", 1, "characters", 0.61)
    assert spend_state(main._spend_summary("local", video_id="p1")) == "Spend: this turn $0.00 · video $0.61 · project $0.61"
    assert spend_state(main._spend_summary("local", video_id="p2")) == "Spend: this turn $0.00 · video $0.00"

    from tests.agent.conftest import reply, use, text as said
    from tests.api.test_endpoints import _agent_on
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [reply(use("project_state", "s1"), stop="tool_use"), reply(said("Fine."))])
    send(client, "hi")
    said_back = str(scripted.calls[1]["messages"][-1]["content"])
    # The first call's thinking (a tenth of a cent) is this turn's, and the video's.
    assert "Spend: this turn $0.00 · video $0.61 · project $0.61" in said_back
    assert "Money figures you mention come from project_state; never work them out yourself." in str(scripted.calls[0]["system"])
