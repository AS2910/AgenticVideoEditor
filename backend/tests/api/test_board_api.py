"""C1 through the API: manual stage moves (one event each), the warning
before an add lands on an Approved video, the drop back to Draft once it
does, a reviewer link putting a video In review, and the feed's "You"."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from app.store import stages
from app.store.actors import user
from tests.api.test_endpoints import upload, voiced
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


def moves(client, project_id="f1"):
    return [e for e in client.get(f"/projects/{project_id}/events").json()["events"] if e["verb"] == "stage.moved"]


def test_a_manual_move_writes_exactly_one_event(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video, "f1")
    resp = client.post("/videos/p1/stage", json={"to": "approved"})
    assert resp.status_code == 200
    assert (resp.json()["stage"], resp.json()["label"], resp.json()["moved"]) == ("approved", "Approved", True)
    [one] = moves(client)
    assert (one["payload"]["from"], one["payload"]["to"], one["you"]) == ("draft", "approved", True)
    again = client.post("/videos/p1/stage", json={"to": "approved"}).json()
    assert again["moved"] is False and len(moves(client)) == 1                 # no move, no event
    assert client.post("/videos/p1/stage", json={"to": "done"}).status_code == 422
    assert client.post("/videos/p9/stage", json={"to": "draft"}).status_code == 404
    assert client.get("/projects/f1/videos").json()["videos"][0]["stage"] == "approved"
    assert client.get("/projects/f1/videos").json()["videos"][0]["open_comments"] == 0
    flags.set("projects.review", "local", False)
    assert client.post("/videos/p1/stage", json={"to": "draft"}).status_code == 404


def test_adding_to_an_approved_video_warns_first_then_drops_it_to_draft_and_logs_it(client, sample_video, monkeypatch):
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video, "f1")
    plan_id = voiced(client, monkeypatch)["plan"]["plan_id"]
    stages.move(database, "p1", "approved", user("local"))
    assert client.get("/videos/p1").json()["stage"] == "approved"
    refused = client.post(f"/videos/p1/plans/{plan_id}/approve", json={"items": ["i1"]})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "stage_approved" and detail["videos"] == ["p1"]
    assert detail["message"] == "This video is Approved. Adding this moves it back to Draft."
    assert client.get("/videos/p1").json()["edits"] == [] and stages.current(database, "p1") == "approved"
    shipped = client.post(f"/videos/p1/plans/{plan_id}/approve", json={"items": ["i1"], "confirm_stage": True})
    assert shipped.status_code == 200 and [a["edit_id"] for a in shipped.json()["approved"]] == ["e1"]
    assert stages.current(database, "p1") == "draft"
    last = moves(client)[0]
    assert (last["payload"]["from"], last["payload"]["to"]) == ("approved", "draft")
    assert last["payload"]["why"] == "A new edit was added after approval."
    verbs = [e["verb"] for e in client.get("/videos/p1/events/log").json()["events"]]
    assert verbs[:2] == ["stage.moved", "edit.shipped"]


def test_with_the_flag_off_an_add_is_not_held_but_still_leaves_approved(client, sample_video, monkeypatch):
    upload(client, sample_video)
    plan_id = voiced(client, monkeypatch)["plan"]["plan_id"]
    stages.move(database, "p1", "approved", user("local"))
    flags.set("projects.review", "local", False)
    assert client.post(f"/videos/p1/plans/{plan_id}/approve", json={}).status_code == 200
    assert stages.current(database, "p1") == "draft"


def test_a_reviewer_link_puts_the_video_in_review_and_a_viewer_link_does_not(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1", name="b.mp4")
    assert client.post("/projects/f1/shares", json={"scope": "video", "target": "p1"}).status_code == 201
    assert stages.current(database, "p1") == "draft"
    made = client.post("/projects/f1/shares", json={"scope": "video", "target": "p1", "role": "reviewer", "name": "Priya"})
    assert made.status_code == 201 and stages.current(database, "p1") == "in_review"
    assert moves(client)[0]["payload"]["why"] == "Review link sent to Priya."
    client.post("/projects/f1/shares", json={"scope": "project", "role": "reviewer"})
    assert stages.current(database, "p2") == "in_review" and len(moves(client)) == 2
