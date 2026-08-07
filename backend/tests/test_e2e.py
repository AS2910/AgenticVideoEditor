import pytest
from fastapi.testclient import TestClient
from app.api.main import app, repo


@pytest.fixture(autouse=True)
def reset_repo():
    repo.reset()
    yield


def test_full_journey_ingest_preview_approve_export():
    client = TestClient(app)

    # 1. Ingest
    created = client.post("/projects", json={"filename": "summer-sale.mp4", "duration": 30.0})
    project_id = created.json()["project_id"]

    # 2. Preview an edit (change the offer)
    payload = {
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    }
    preview = client.post(f"/projects/{project_id}/edits/preview", json=payload).json()
    assert preview["plan"]["new_text"] == "30% off"
    assert preview["continuity"]["passed"] is True

    # 3. Approve it
    approved = client.post(f"/projects/{project_id}/edits", json=payload).json()
    assert approved["edit_id"] == "e1"

    # 4. Export shows the edited span composited between original footage
    segments = client.post(f"/projects/{project_id}/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["start"] == 0.4 and edited[0]["end"] == 1.3
