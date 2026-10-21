"""G6 through the API (golive.g6 on): consent needs a passed read-aloud
attempt; a known public figure is not cloned (a voice's name, and a
speaker's line falls back to the stock voice with the sentence); withdraw
consent now deletes the clone at once; the public abuse form stores, tells
the admins and is rate limited; your data export is an Activity job with a
zip; a deletion request is kept as a record; the Export page's file carries
the mark and a manifest; flag off 404."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import safety_api
from app.api.main import app, database, flags, jobs, repo
from app.domain.models import Selection
from app.media import ffmpeg
from app.notify.email import outbox
from app.safety import figures
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    repo.reset()
    jobs.reset()
    safety_api.abuse_limit.reset()
    monkeypatch.setattr(main, "DATA_EXPORT_IN_BACKGROUND", False)
    flags.set("golive.g6", "local", True)
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def video(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    with open(sample_video, "rb") as f:
        made = client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "false", "project_id": "f1"})
    assert made.status_code == 200, made.text
    return "p1"



def test_consent_needs_the_sentence_read_aloud(client, video, sample_video):
    assert client.post("/videos/p1/consent").status_code == 422
    start = client.post("/videos/p1/liveness", json={"speaker": "Host"}).json()
    assert "My code is" in start["sentence"] and start["test_mode"]
    with open(sample_video, "rb") as f:                                  # a recording with sound: passes in test mode
        checked = client.post(f"/videos/p1/liveness/{start['attempt_id']}", files={"file": ("me.mp4", f, "video/mp4")}).json()
    assert checked["status"] == "passed" and "test mode" in checked["reason"]
    again = client.post(f"/videos/p1/liveness/{start['attempt_id']}", files={"file": ("me.mp4", io.BytesIO(b"x"), "video/mp4")})
    assert again.status_code == 409                                       # one recording per sentence
    bad = client.post("/videos/p1/liveness", json={}).json()
    failed = client.post(f"/videos/p1/liveness/{bad['attempt_id']}", files={"file": ("x.webm", io.BytesIO(b"nope"), "audio/webm")}).json()
    assert failed["status"] == "failed"
    assert client.post("/videos/p1/consent", json={"liveness_id": bad["attempt_id"]}).status_code == 422
    ok = client.post("/videos/p1/consent", json={"liveness_id": start["attempt_id"]})
    assert ok.status_code == 200 and ok.json()["consent_granted_at"]
    with database.tx() as c:
        row = c.execute("SELECT status, audio_sha, speaker FROM liveness_attempts WHERE id = ?", (start["attempt_id"],)).fetchone()
    assert row["status"] == "passed" and row["audio_sha"] and row["speaker"] == "Host"


def test_a_public_figure_is_not_cloned(client, video, monkeypatch):
    refused = client.post("/voices/mine/from-speaker", json={"video_id": "p1", "label": "A", "name": "Narendra Modi", "consent": True})
    assert refused.status_code == 422 and refused.json()["detail"] == figures.REFUSAL
    monkeypatch.setattr(main, "_speakers", lambda vid: [{"label": "A", "name": "Shah Rukh Khan", "voice_id": None}])
    record = repo.get("p1")
    choice = main._voice_for("p1", record, Selection(0.4, 1.3), "mock", speaker="A")
    assert choice.voice_id == "mock" and not choice.cloned and figures.REFUSAL in choice.notes[0]


def test_withdraw_consent_now_deletes_the_clone_at_once(client, video, monkeypatch):
    deleted = []
    monkeypatch.setattr(main.voice, "delete_clone", lambda vid: deleted.append(vid), raising=False)
    repo.grant_consent("p1", main.Consent(granted_at=main._now()))
    repo.set_clone("p1", "A", "clone-123")
    out = client.post("/videos/p1/consent/withdraw").json()
    assert out == {"withdrawn": True, "deleted": 1, "failed": [], "said": "Consent withdrawn. The speaker's voice clone was deleted at the voice service."}
    assert deleted == ["clone-123"] and repo.clones("p1") == {} and repo.get("p1").consent is None
    feed = client.get("/videos/p1/events/log").json()["events"]
    assert feed[0]["verb"] == "consent.withdrawn"
    assert client.post("/videos/p1/consent/withdraw").json()["said"] == "Consent withdrawn. There was no voice clone to delete."


def test_abuse_reports_are_public_stored_told_and_limited(client):
    sent = client.post("/abuse-reports", json={"location": "http://x/#s/tok", "kind": "impersonation", "details": "Not my voice", "contact": "a@b.c"})
    assert sent.status_code == 201 and sent.json()["said"] == "Thank you. We read every report and act on it."
    bell = client.get("/me/notifications").json()["items"]
    assert bell[0]["kind"] == "abuse_report" and bell[0]["title"].startswith("Abuse report #1")
    assert outbox(database, kind="abuse_report")[-1]["to_addr"] == main.settings.trust_email
    assert client.get("/admin/analytics").json()["abuse_reports"][0]["details"] == "Not my voice"
    with database.tx() as c:
        assert c.execute("SELECT owner FROM analytics_events WHERE name = 'abuse.reported'").fetchone()[0] == "public"
    assert client.post("/abuse-reports", json={"location": "x", "kind": "nope"}).status_code == 422
    for _ in range(4):
        client.post("/abuse-reports", json={"location": "x", "kind": "other"})
    assert client.post("/abuse-reports", json={"location": "x", "kind": "other"}).status_code == 429


def test_your_data_export_is_a_job_with_a_zip_and_deletion_is_recorded(client, video):
    made = client.post("/me/data-export").json()["request"]
    assert made["kind"] == "export" and made["status"] == "done" and made["job"]["status"] == "done"
    listed = client.get("/me/data-export").json()["requests"]
    assert listed[0]["job"]["kind"] == "data_export"
    got = client.get(f"/me/data-export/{made['job_id']}/download")
    assert got.status_code == 200
    with zipfile.ZipFile(io.BytesIO(got.content)) as z:
        assert [v["id"] for v in json.loads(z.read("videos.json"))] == ["p1"]
        assert any(m["store"] == "p1" for m in json.loads(z.read("media.json")))
    assert client.get("/me/data-export/nope/download").status_code == 404
    assert client.delete("/account").status_code == 204
    with database.tx() as c:
        kinds = [r[0] for r in c.execute("SELECT kind FROM data_requests WHERE owner = 'local' ORDER BY id")]
    assert kinds == ["export", "deletion"]


def test_the_export_carries_the_mark_and_a_manifest(client, video):
    out = client.post("/videos/p1/export", json={"purpose": "export"}).json()
    marked = out["render"]["sha256"]
    assert out["provenance"]["mark"] and out["provenance"]["source_sha256"] != marked
    path = main.artifacts.find("p1", marked)
    assert main.watermarker.read(Path(path)) == out["provenance"]["mark"]
    manifest = client.get(f"/videos/p1/artifacts/{marked}/c2pa").json()
    assert manifest["manifest"]["asset"]["sha256"] == marked and manifest["signature"]["test_mode"]
    assert client.get(f"/exports/provenance/{out['provenance']['mark']}").json()["video_id"] == "p1"
    again = client.post("/videos/p1/export", json={"purpose": "export"}).json()
    assert again["render"]["sha256"] == marked                            # once per render


def test_flag_off(client, video):
    flags.set("golive.g6", "local", False)
    assert client.post("/videos/p1/liveness", json={}).status_code == 404
    assert client.post("/me/data-export").status_code == 404
    assert client.post("/videos/p1/consent").status_code == 200          # consent as before
    out = client.post("/videos/p1/export", json={"purpose": "export"}).json()
    assert "provenance" not in out
