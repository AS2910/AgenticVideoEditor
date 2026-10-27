"""Run 5 item 5: the editor's simple view is the default, and "More controls"
is remembered per user, server-side, never copied into a video."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg
from tests.api.test_endpoints import upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


def test_more_controls_is_off_until_the_user_turns_it_on_and_is_remembered(sample_video):
    client = TestClient(app)
    assert upload(client, sample_video).status_code == 200
    # New and existing users alike start in the simple view.
    assert client.get("/me/settings").json()["more_controls"] is False
    assert client.get("/videos/p1").json()["settings"]["more_controls"] is False
    # Turned on: kept for the user, and every video reads it.
    assert client.put("/me/settings", json={"more_controls": True}).json()["more_controls"] is True
    assert client.get("/me/settings").json()["more_controls"] is True
    assert client.get("/videos/p1/settings").json()["settings"]["more_controls"] is True
    assert client.get("/videos/p1").json()["settings"]["more_controls"] is True
    assert "more_controls" not in repo.settings("p1")
    # Another setting saved later leaves it as it was.
    assert client.put("/me/settings", json={"ask_over_usd": 0.3}).json()["more_controls"] is True
    assert client.put("/me/settings", json={"more_controls": False}).json()["more_controls"] is False
