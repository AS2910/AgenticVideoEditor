"""Run 5, item 10: the upload looks at each line; the project's statements,
/health, Voltage's transcript and the admin review page read it."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import lipsync_api
from app.api.main import app, jobs, repo
from app.media import ffmpeg

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
H = {"X-Requested-With": "voltage"}


@pytest.fixture()
def client(monkeypatch):
    repo.reset()
    jobs.reset()
    monkeypatch.setenv("AVE_ON_CAMERA", "1")
    monkeypatch.setattr(lipsync_api, "IN_BACKGROUND", False)
    return TestClient(app)


def _upload(client, path):
    with open(path, "rb") as handle:
        out = client.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=H)
    assert out.status_code == 200, out.text
    return out.json()


def test_an_upload_tells_each_line_whether_its_speaker_is_seen(client, sample_video):
    made = _upload(client, sample_video)
    assert made["statements"] and all(st["on_camera"] == "off_camera" for st in made["statements"])
    record = client.get(f"/videos/{made['video_id']}/on-camera").json()
    assert record["status"] == "done" and record["seconds"] < 10
    assert record["lines"][0]["why"] == "No face on screen for this line."


def test_switched_off_the_upload_does_not_look(client, sample_video, monkeypatch):
    monkeypatch.setenv("AVE_ON_CAMERA", "0")
    made = _upload(client, sample_video)
    assert all(st["on_camera"] is None for st in made["statements"])
    assert client.get(f"/videos/{made['video_id']}/on-camera").json()["status"] == "none"


def test_look_again_fills_an_old_video(client, sample_video, monkeypatch):
    monkeypatch.setenv("AVE_ON_CAMERA", "0")
    made = _upload(client, sample_video)
    monkeypatch.setenv("AVE_ON_CAMERA", "1")
    again = client.post(f"/videos/{made['video_id']}/on-camera", headers=H).json()
    assert again["status"] == "done"
    assert all(st["on_camera"] == "off_camera" for st in client.get(f"/videos/{made['video_id']}").json()["statements"])


def test_health_says_no_lip_sync_provider_is_on(client):
    assert client.get("/health").json()["lipsync"] == "off"


def test_voltage_reads_which_lines_are_on_camera(client, sample_video):
    from app.agent.tools import CAMERA_NOTE, CAMERA_TAGS
    made = _upload(client, sample_video)
    vid = made["video_id"]
    st = made["statements"][0]
    repo.set_settings(vid, on_camera={"status": "done", "lines": [
        {"start": st["start"], "end": st["end"], "state": "on_camera"}]})
    lines = main._lines(repo.get(vid))
    assert lines[0].on_camera == "on_camera"
    from app.agent import tools
    text = tools._read_transcript(_Workbench(), _Turn(repo.get(vid)), {}).text
    assert CAMERA_TAGS["on_camera"].strip() in text and CAMERA_NOTE in text
    assert "lips won't match yet" in CAMERA_NOTE


class _Workbench:
    def lines(self, record):
        return main._lines(record)

    def speakers(self, project_id):
        return []


class _Turn:
    def __init__(self, record):
        self.record, self.project_id = record, record.source.project_id


def test_the_review_page_is_for_admins_only(client, sample_video, monkeypatch):
    made = _upload(client, sample_video)
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=("google:someone-else",)))
    assert client.get("/admin/lipsync").status_code == 404
    assert client.get(f"/admin/lipsync/videos/{made['video_id']}").status_code == 404


@pytest.fixture()
def admin(client, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, admin_owners=(main.LOCAL_OWNER,)))
    return client


def test_an_admin_runs_a_line_through_the_fake_and_sees_both_sides_scored(admin, sample_video):
    made = _upload(admin, sample_video)
    vid = made["video_id"]
    status = admin.get("/admin/lipsync").json()
    assert status["selected"] == "off" and status["handle_seconds"] == 0.5 and status["measure"] == "motion"
    page = admin.get(f"/admin/lipsync/videos/{vid}").json()
    assert page["status"] == "done" and page["lines"][0]["on_camera"] == "off_camera"
    trial = admin.post(f"/admin/lipsync/videos/{vid}/trials", json={"line": 1, "provider": "fake"}, headers=H)
    assert trial.status_code == 200, trial.text
    t = trial.json()
    assert t["provider"] == "fake" and t["usd"] == 0 and t["heard"].startswith("the line's own sound")
    assert t["window"]["send_start"] <= t["window"]["start"]
    assert t["compare"]["verdict"] == "no_face"
    for side in ("original", "result"):
        got = admin.get(f"/admin/lipsync/videos/{vid}/files/{t[side]['sha256']}")
        assert got.status_code == 200 and got.headers["content-type"] == "video/mp4"
    assert admin.get(f"/admin/lipsync/videos/{vid}").json()["trials"][0]["id"] == t["id"]


def test_a_real_provider_that_is_off_is_refused_in_words(admin, sample_video):
    vid = _upload(admin, sample_video)["video_id"]
    out = admin.post(f"/admin/lipsync/videos/{vid}/trials", json={"line": 1, "provider": "sync_so"}, headers=H)
    assert out.status_code == 422 and "off" in out.json()["detail"]
    out = admin.post(f"/admin/lipsync/videos/{vid}/trials", json={"line": 9, "provider": "fake"}, headers=H)
    assert out.status_code == 422 and "Pick a line" in out.json()["detail"]
