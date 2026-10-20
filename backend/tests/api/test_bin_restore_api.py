"""D3 through the API: the Bin lists what was deleted with who and the days
left; Restore puts it back (a video into its project, or standalone when
the project is in the Bin or gone; a project with the videos deleted with
it; a voice pickable again); everything made on it comes back."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ffmpeg
from tests.api.test_endpoints import purge_now, upload
from tests.api.test_folders import upload_into
from tests.store.test_repository import make_edit

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def bin_items(client):
    resp = client.get("/bin")
    assert resp.status_code == 200, resp.text
    return {(i["kind"], i["id"]): i for i in resp.json()["items"]}


def test_restore_brings_back_turns_edits_and_renders(client, sample_video):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring"})
    assert upload_into(client, sample_video, "f1").status_code == 200
    repo.append_edit("p1", make_edit("e1"))
    repo.append_turn("p1", "user", "Make it warmer")
    repo.add_message("p1", "user", "Make it warmer")
    render = main.artifacts.root / "p1" / "render-abc.mp4"
    render.write_bytes(b"mp4")
    repo.set_settings("p1", renders={"abc": {"path": "render-abc.mp4", "version": 1}})

    assert client.delete("/videos/p1").status_code == 204
    assert client.get("/videos/p1").status_code == 404
    item = bin_items(client)[("video", "p1")]
    assert item["name"] == "ad.mp4" and item["days_left"] == 30 and item["deleted_by_you"]
    assert item["project_name"] == "Spring" and not item["project_in_bin"]

    done = client.post("/bin/video/p1/restore")
    assert done.status_code == 200 and done.json()["project_id"] == "f1" and done.json()["standalone_because"] is None
    body = client.get("/videos/p1").json()
    assert body["project_id"] == "f1"
    assert [e.edit_id for e in repo.list_edits("p1")] == ["e1"]
    assert repo.turns("p1") == [{"role": "user", "content": "Make it warmer"}]
    assert [m["text"] for m in client.get("/videos/p1/messages").json()] == ["Make it warmer"]
    assert repo.settings("p1")["renders"]["abc"]["version"] == 1 and render.exists()
    assert bin_items(client) == {}
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert verbs[0] == "video.restored" and "video.deleted" in verbs
    assert client.post("/bin/video/p1/restore").status_code == 404


def test_a_project_comes_back_with_the_videos_deleted_with_it(client, sample_video):
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1", name="one.mp4")
    upload_into(client, sample_video, "f1", name="two.mp4")
    assert client.delete("/videos/p1").status_code == 204          # on its own, first
    assert client.delete("/projects/f1", params={"videos": "delete"}).status_code == 204
    items = bin_items(client)
    assert items[("project", "f1")]["videos"] == 1
    assert items[("video", "p2")]["project_in_bin"] and items[("video", "p2")]["with_project"]
    assert not items[("video", "p1")]["with_project"]

    done = client.post("/bin/project/f1/restore").json()
    assert done["videos"] == ["p2"]
    assert [v["video_id"] for v in client.get("/projects/f1/videos").json()["videos"]] == ["p2"]
    assert set(bin_items(client)) == {("video", "p1")}           # deleted on its own: still in the Bin


def test_a_video_whose_project_is_binned_or_gone_comes_back_standalone(client, sample_video):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring"})
    client.post("/projects", json={"name": "Autumn"})
    upload_into(client, sample_video, "f1", name="one.mp4")
    upload_into(client, sample_video, "f2", name="two.mp4")
    client.delete("/projects/f1", params={"videos": "delete"})
    done = client.post("/bin/video/p1/restore").json()
    assert done["project_id"] is None and "Spring is in the Bin" in done["standalone_because"]
    assert client.get("/videos/p1").json()["project_id"] is None

    client.delete("/videos/p2")
    with main.database.tx() as c:   # its project went for good meanwhile (the purge took it)
        c.execute("DELETE FROM projects WHERE id = 'f2'")
    done = client.post("/bin/video/p2/restore").json()
    assert done["project_id"] is None and "gone" in done["standalone_because"]
    assert client.get("/videos/p2").json()["project_id"] is None


def test_a_restored_voice_can_be_picked_again(client):
    import app.api.main as main
    main._set_my_voices("local", [{"voice_id": "V1", "name": "Mine", "seconds": 3.0, "at": main._now(),
                                   "kind": "recorded", "consent_granted_at": main._now()}])
    assert client.delete("/voices/mine/V1").status_code == 204
    item = bin_items(client)[("voice", "V1")]
    assert item["name"] == "Mine" and item["consent"] and item["days_left"] == 30
    # In the Bin: in no list a voice is picked from (the catalogue, my voices, Voltage's tools).
    assert client.get("/voices").json()["mine"] == []
    assert [v["voice_id"] for v in main._workbench().mine("local")] == []
    assert client.post("/bin/voice/V1/restore").status_code == 200
    assert [v["voice_id"] for v in client.get("/voices").json()["mine"]] == ["V1"]
    assert [v["voice_id"] for v in main._workbench().mine("local")] == ["V1"]


def test_the_bin_is_behind_its_flag(client):
    import app.api.main as main
    main.flags.set("projects.reuse", "local", False)
    try:
        assert client.get("/bin").status_code == 404
        assert client.post("/bin/video/p1/restore").status_code == 404
    finally:
        main.flags.clear("projects.reuse", "local")


def test_usage_counts_only_live_videos_by_project(client, sample_video):
    import app.api.main as main
    client.post("/projects", json={"name": "Spring"})
    upload_into(client, sample_video, "f1", name="one.mp4")
    upload_into(client, sample_video, "f1", name="two.mp4")
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.5)
    client.delete("/videos/p1")
    usage = client.get("/usage", params={"period": "all"}).json()
    row = next(p for p in usage["by_project"] if p["project_id"] == "f1")
    assert row["videos"] == 1
    assert usage["spent_usd"] == pytest.approx(0.5)            # its spend still counts
    assert any(v["video_id"] == "p1" for v in usage["by_video"])


def test_purge_after_30_days_removes_storage_and_keeps_consent(client, sample_video):
    import app.api.main as main
    from app.purge import consent_records
    assert upload(client, sample_video).status_code == 200      # uploaded with consent
    stored = main.artifacts.root / "p1"
    assert stored.is_dir()
    main._set_my_voices("local", [{"voice_id": "V1", "name": "Mine", "seconds": 3.0, "at": main._now(),
                                   "kind": "recorded", "consent_granted_at": "2026-10-01T00:00:00.000Z"}])
    client.delete("/videos/p1")
    client.delete("/voices/mine/V1")
    report = purge_now(main)
    assert report.videos == ["p1"] and str(stored) in report.storage and not stored.exists()
    assert sorted(report.consent_kept) == ["video:p1", "voice:local:V1"]
    assert bin_items(client) == {}
    kept = {(r["kind"], r["item_id"]): r for r in consent_records(main.database, "local")}
    assert kept[("voice", "local:V1")]["consent"]["granted_at"] == "2026-10-01T00:00:00.000Z"
    assert kept[("video", "p1")]["consent"]["granted_at"]
    assert client.post("/bin/video/p1/restore").status_code == 404
