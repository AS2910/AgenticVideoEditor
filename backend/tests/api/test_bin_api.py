"""F8 through the API: deleting a video, a project or a voice moves it to
the Bin: hidden from every list and get, its charges still in Usage."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import purge_now, upload
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def test_deleted_items_are_hidden_and_their_charges_keep_their_names(client, sample_video):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1")
    upload(client, sample_video, name="alone.mp4")
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.5)
    spent = client.get("/usage", params={"period": "all"}).json()
    assert client.delete("/projects/f1", params={"videos": "delete"}).status_code == 204
    assert client.get("/projects").json()["projects"] == []
    assert client.get("/projects/f1").status_code == 404 and client.get("/videos/p1").status_code == 404
    assert [v["video_id"] for v in client.get("/videos").json()["videos"]] == ["p2"]
    assert client.delete("/projects/f1", params={"videos": "delete"}).status_code == 404

    def usage_names():
        body = client.get("/usage", params={"period": "all"}).json()
        return body, {(g["name"], v["filename"]) for g in body["groups"] for v in g["videos"]}
    body, names = usage_names()
    assert ("Spring", "ad.mp4") in names and body["spent_usd"] == spent["spent_usd"] > 0
    purge_now(main)
    body, names = usage_names()
    assert ("Spring", "ad.mp4") in names and body["spent_usd"] == spent["spent_usd"] > 0


def test_a_deleted_voice_is_hidden_and_cannot_be_picked(client):
    import app.api.main as main
    main._set_my_voices("local", [{"voice_id": "V1", "name": "Mine", "seconds": 3.0, "at": main._now(), "kind": "recorded"}])
    client.post("/projects", json={"name": "Spring"})
    assert client.delete("/voices/mine/V1").status_code == 204
    assert client.get("/voices").json()["mine"] == []
    assert client.post("/projects/f1/voices", json={"voice_id": "V1"}).status_code == 404
    assert client.delete("/voices/mine/V1").status_code == 404
    # Writing the live list keeps the one in the Bin for the purge.
    main._set_my_voices("local", [{"voice_id": "V2", "name": "New", "seconds": 1.0, "at": main._now()}])
    assert [v["voice_id"] for v in main._all_my_voices("local")] == ["V2", "V1"]
