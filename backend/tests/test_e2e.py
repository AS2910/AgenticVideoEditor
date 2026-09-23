import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


def test_full_journey_ingest_preview_approve_export(sample_video):
    client = TestClient(app)

    # 1. Ingest a real file; its duration is measured, not claimed
    with open(sample_video, "rb") as handle:
        created = client.post(
            "/projects",
            files={"file": ("summer-sale.mp4", handle, "video/mp4")},
            data={"consent": "true"},  # the UI gates on this before upload
        ).json()
    project_id = created["project_id"]
    assert created["duration"] == pytest.approx(2.3, abs=0.05)
    assert created["consent"] is not None

    # The uploaded video is served straight back, seekable
    media = client.get(f"/projects/{project_id}/artifacts/{created['media']['sha256']}")
    assert media.status_code == 200

    # 2. Preview an edit (change the offer)
    payload = {
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    }
    accepted = client.post(f"/projects/{project_id}/edits/preview", json=payload)
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]

    # 2b. Poll the job to completion, as the UI does
    deadline = time.time() + 10
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.01)
    assert job["status"] == "succeeded", job

    preview = job["result"]
    assert preview["plan"]["new_text"] == "30% off"
    assert preview["continuity"]["passed"] is True

    # 3. Approve that exact candidate
    approved = client.post(
        f"/projects/{project_id}/edits", json={"candidate_id": preview["candidate_id"]},
    ).json()
    assert approved["edit_id"] == "e1"

    # 4. Export shows the edited span composited between original footage
    segments = client.post(f"/projects/{project_id}/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["start"] == 0.4 and edited[0]["end"] == 1.3

    # 5. The edited span resolves to media that actually exists on disk
    committed = repo.list_edits(project_id)[0]
    assert edited[0]["artifact"]["sha256"] == committed.frames.sha256
    assert Path(committed.frames.path).is_file()
    assert Path(committed.audio.path).is_file()
