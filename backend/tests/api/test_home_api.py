"""D4 through the API: pins per user, archived projects (hidden from Home,
searchable, read-only with one clear sentence) and search grouped by
project, a transcript hit carrying the time its word is said."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from app.store.home import ARCHIVED
from tests.api.test_endpoints import upload
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


def test_an_archived_project_blocks_new_turns_with_a_clear_message(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    assert client.post("/projects/f1/archive").status_code == 200
    turn = client.post("/videos/p1/turns", json={"text": "Make it warmer"})
    assert turn.status_code == 423 and turn.json()["detail"] == ARCHIVED == "This project is archived. Unarchive it to make changes."
    # Edits, uploads into it, moves into it and project changes are refused the same way.
    assert client.post("/videos/p1/edits", json={}).json()["detail"] == ARCHIVED
    assert upload_into(client, sample_video, "f1").json()["detail"] == ARCHIVED
    assert upload(client, sample_video, name="alone.mp4").status_code == 200
    assert client.patch("/videos/p2", json={"project_id": "f1"}).json()["detail"] == ARCHIVED
    assert client.patch("/projects/f1", json={"brief": "New"}).json()["detail"] == ARCHIVED
    # Reading still works, and it is hidden from Home's list but found with ?archived=true.
    assert client.get("/videos/p1").status_code == 200
    assert client.get("/projects").json()["projects"] == []
    archived = client.get("/projects", params={"archived": "true"}).json()["projects"]
    assert [p["project_id"] for p in archived] == ["f1"] and archived[0]["archived_at"]
    summary = next(v for v in client.get("/videos").json()["videos"] if v["video_id"] == "p1")
    assert summary["project_archived"] is True
    # Unarchive: writable again.
    assert client.delete("/projects/f1/archive").status_code == 200
    assert client.patch("/projects/f1", json={"brief": "New"}).status_code == 200
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert "project.archived" in verbs and "project.unarchived" in verbs


def test_transcript_search_finds_a_spoken_word_and_its_time(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1")
    words = repo.get("p1").transcript.words
    target = next(w for w in words if len(w.text.strip(" .,!?")) > 3)
    word = target.text.strip(" .,!?")
    found = client.get("/search", params={"q": word.upper()}).json()
    group = next(g for g in found["groups"] if g["project_id"] == "f1")
    hit = next(h for h in group["hits"] if h["kind"] == "transcript")
    assert hit["video_id"] == "p1" and hit["at"] == pytest.approx(target.start)
    assert word.lower() in hit["text"].lower() and hit["filename"] == "ad.mp4"


def test_search_groups_by_project_and_covers_names_briefs_and_archived(client, sample_video):
    client.post("/projects", json={"name": "Diwali offer"})
    client.patch("/projects/f1", json={"brief": "Say the Diwali price clearly."})
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f2", name="diwali-teaser.mp4")
    upload(client, sample_video, name="alone.mp4")
    client.post("/projects/f1/archive")
    found = client.get("/search", params={"q": "diwali"}).json()
    by = {g["project_id"]: g for g in found["groups"]}
    assert {h["kind"] for h in by["f1"]["hits"]} == {"project", "brief"} and by["f1"]["archived"]
    assert [h["kind"] for h in by["f2"]["hits"]] == ["video"]
    assert client.get("/search", params={"q": "x"}).json()["groups"] == []
    client.delete("/videos/p1")
    assert "f2" not in {g["project_id"] for g in client.get("/search", params={"q": "diwali"}).json()["groups"]}


def test_pins_are_per_user_and_skip_deleted_items(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    upload(client, sample_video, name="alone.mp4")
    assert client.put("/pins/project/f1").status_code == 200
    assert client.put("/pins/video/p1").status_code == 200
    assert client.put("/pins/video/p9").status_code == 404
    assert [(p["kind"], p["id"], p["name"]) for p in client.get("/pins").json()["pins"]] == [
        ("project", "f1", "Spring"), ("video", "p1", "alone.mp4")]
    import app.api.main as main
    from app.store import home
    assert home.pins(main.database, "someone-else") == []
    client.delete("/videos/p1")
    assert [p["id"] for p in client.get("/pins").json()["pins"]] == ["f1"]
    assert client.delete("/pins/project/f1").status_code == 200
    assert client.get("/pins").json()["pins"] == []


def test_d4_routes_are_behind_the_flag(client):
    import app.api.main as main
    main.flags.set("projects.reuse", "local", False)
    try:
        assert client.get("/search", params={"q": "ad"}).status_code == 404
        assert client.get("/pins").status_code == 404
        assert client.post("/projects/f1/archive").status_code == 404
    finally:
        main.flags.clear("projects.reuse", "local")
