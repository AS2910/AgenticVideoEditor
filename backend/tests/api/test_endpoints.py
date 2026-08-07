import pytest
from fastapi.testclient import TestClient
from app.api.main import app, repo


@pytest.fixture(autouse=True)
def reset_repo():
    repo.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def create_project(client):
    resp = client.post("/projects", json={"filename": "ad.mp4", "duration": 30.0})
    assert resp.status_code == 200
    return resp.json()


def test_create_project_returns_id_and_transcript(client):
    body = create_project(client)
    assert body["project_id"] == "p1"
    assert body["transcript"][0]["text"] == "Get"


def test_preview_returns_candidate_with_continuity(client):
    create_project(client)
    resp = client.post("/projects/p1/edits/preview", json={
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"]["new_text"] == "30% off"
    assert body["plan"]["selection"] == {"start": 0.4, "end": 1.3}  # snapped
    assert body["continuity"]["passed"] is True


def test_preview_unknown_project_is_404(client):
    resp = client.post("/projects/nope/edits/preview", json={
        "prompt": "hi", "start": 0.0, "end": 1.0, "voice_profile_id": "speaker-1",
    })
    assert resp.status_code == 404


def test_approve_appends_edit_and_export_shows_it(client):
    create_project(client)
    payload = {
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
    }
    approve = client.post("/projects/p1/edits", json=payload)
    assert approve.status_code == 200
    assert approve.json()["edit_id"] == "e1"

    export = client.post("/projects/p1/export")
    kinds = [(s["kind"]) for s in export.json()["segments"]]
    assert kinds == ["original", "edited", "original"]


def test_approve_rejected_when_continuity_fails(client):
    create_project(client)
    resp = client.post("/projects/p1/edits", json={
        "prompt": 'change "20% off" to "30% off"',
        "start": 0.5, "end": 1.0, "voice_profile_id": "unknown",
    })
    assert resp.status_code == 422
