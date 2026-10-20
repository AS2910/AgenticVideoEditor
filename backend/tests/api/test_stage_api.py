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
