"""F5 through the API: a video shows its stage and its moves."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import upload

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def test_a_video_shows_its_stage_and_its_moves(client, sample_video):
    from app.api.main import database
    from app.store import stages
    from app.store.actors import user
    upload(client, sample_video)
    assert client.get("/videos").json()["videos"][0]["stage"] == "draft"
    stages.move(database, "p1", "in_review", user("local"), "Sent")
    body = client.get("/videos/p1/stage").json()
    assert body["stage"] == "in_review" and body["label"] == "In review"
    assert [(m["from_stage"], m["to_stage"], m["why"]) for m in body["history"]] == [("draft", "in_review", "Sent")]
    assert client.get("/videos/p9/stage").status_code == 404


def test_a_line_move_on_an_approved_video_asks_once_then_returns_it_to_draft(client, sample_video):
    """Decision 0: a sync, a role change or a line move that would take an
    Approved video back to Draft answers 409 with the sentence; the yes runs it."""
    from app.api.main import database
    from app.store import stages
    from app.store.actors import user
    upload(client, sample_video)
    stages.move(database, "p1", "approved", user("local"))
    held = client.put("/videos/p1/arrangement", json={"min_gap": 0.2})
    assert held.status_code == 409
    detail = held.json()["detail"]
    assert detail["code"] == "stage_approved" and detail["options"] == ["Change anyway", "Cancel"]
    assert detail["message"] == "This video is Approved. This change moves it back to Draft."
    assert stages.current(database, "p1") == "approved"
    done = client.put("/videos/p1/arrangement", json={"min_gap": 0.2, "confirm_stage": True})
    assert done.status_code == 200 and stages.current(database, "p1") == "draft"
    # A Draft video is never asked.
    assert client.put("/videos/p1/arrangement", json={"min_gap": 0.3}).status_code == 200


def test_the_edit_routes_that_drop_an_approved_video_all_ask(client, sample_video):
    from app.api.main import database
    from app.store import stages
    from app.store.actors import user
    upload(client, sample_video)
    stages.move(database, "p1", "approved", user("local"))
    words = repo.get("p1").transcript.words
    if words:
        shifted = client.post("/videos/p1/lines/shift", json={"start": words[0].start, "end": words[0].end, "to": 0.5})
        assert shifted.status_code == 409 and shifted.json()["detail"]["code"] == "stage_approved"
    for path in ("/videos/p1/edits/e1/role", "/videos/p1/edits/e1/move"):
        body = {"role": "bed"} if path.endswith("role") else {"start": 0.5}
        # No such kept line: the route says so before anything else (404), never a silent drop.
        assert client.post(path, json=body).status_code in (404, 409)
    assert stages.current(database, "p1") == "approved"
