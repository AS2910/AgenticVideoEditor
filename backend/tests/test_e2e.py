"""The whole journey, offline: upload, a turn of Voltage that voices the line
through its tools, approve, export."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, repo, jobs
from tests.api.test_endpoints import _agent_on, take
from tests.factories import media_get


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


def test_full_journey_ingest_turn_approve_export(sample_video, monkeypatch):
    from tests.agent.conftest import reply, text
    client = TestClient(app)

    # 1. Ingest a real file; its duration is measured, not claimed
    with open(sample_video, "rb") as handle:
        created = client.post(
            "/videos",
            files={"file": ("summer-sale.mp4", handle, "video/mp4")},
            data={"consent": "true"},  # the UI gates on this before upload
        ).json()
    project_id = created["video_id"]
    assert created["duration"] == pytest.approx(2.3, abs=0.05)
    assert created["consent_granted_at"] is not None

    # The uploaded video is served straight back, seekable
    media = media_get(client, f"/videos/{project_id}/artifacts/{created['media']['sha256']}")
    assert media.status_code == 200

    # 2. Say what you want; Voltage voices the line through its tools (Just do it)
    client.put(f"/videos/{project_id}/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [
        reply(take(text="Get 30% off today only."), stop="tool_use"),
        reply(text("Line 1 now says 30% off. Hear it; say ship when you're happy.")),
    ])
    accepted = client.post(f"/videos/{project_id}/turns", json={"text": 'change "20% off" to "30% off"'})
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]

    # 2b. Poll the job to completion, as the UI does
    deadline = time.time() + 120
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.01)
    assert job["status"] == "succeeded", job

    result = job["result"]
    assert result["type"] == "turn" and result["reply"].startswith("Line 1 now says 30% off")
    [item] = result["plan"]["items"]
    candidate = item["candidate"]
    assert item["status"] == "ready" and candidate["plan"]["new_text"] == "Get 30% off today only."
    assert candidate["continuity"]["passed"] is True

    # 3. Approve that exact take
    approved = client.post(
        f"/videos/{project_id}/edits", json={"candidate_id": candidate["candidate_id"]},
    ).json()
    assert approved["edit_id"] == "e1"

    # 4. Export shows the edited span; the line is the whole clip, so it is the whole output
    segments = client.post(f"/videos/{project_id}/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["start"] == 0.0 and edited[0]["end"] == 2.3

    # 5. The edited span resolves to media that actually exists on disk
    committed = repo.list_edits(project_id)[0]
    assert edited[0]["artifact"]["sha256"] == committed.frames.sha256
    assert Path(committed.frames.path).is_file()
    assert Path(committed.audio.path).is_file()
