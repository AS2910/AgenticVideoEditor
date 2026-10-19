"""The guided run and what a person has met (Tutorial map and Help, 2026-10-19):
the sample ad as a tutorial video whose turns replay a recording for free,
and the onboarding record behind the tour, the tips and the checklist."""
import time

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def await_job(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_onboarding_starts_empty_and_merges_what_is_seen(client):
    assert client.get("/me/onboarding").json() == {
        "tour": {"step": 0, "finished": False, "skipped": False}, "tips": [], "checklist": [], "checklist_hidden": False,
    }
    r = client.put("/me/onboarding", json={"tips": ["first-upload"], "tour": {"step": 3}})
    assert r.status_code == 200 and r.json()["tips"] == ["first-upload"] and r.json()["tour"]["step"] == 3
    # A tip once seen stays seen; the checklist is a union too; unknown ids are dropped; the flag replaces.
    r = client.put("/me/onboarding", json={"tips": ["first-question", "nope"], "checklist": ["goal"], "checklist_hidden": True, "tour": {"finished": True}})
    body = r.json()
    assert body["tips"] == ["first-upload", "first-question"]
    assert body["checklist"] == ["goal"] and body["checklist_hidden"] is True
    assert body["tour"] == {"step": 3, "finished": True, "skipped": False}


def test_the_tutorial_replays_the_recorded_run_without_spending(client):
    made = client.post("/tutorial")
    assert made.status_code == 201, made.text
    video = made.json()
    vid = video["video_id"]
    assert video["filename"] == "sample-ad.mp4"
    assert [s["text"] for s in video["statements"]] == ["Get 20% off today only."]
    assert video["settings"]["tutorial"] is True
    assert video["reading"]["opening"]
    assert client.get(f"/videos/{vid}/usage").json()["spent_usd"] == 0

    # Turn 1: the recorded steps, then the gate.
    job = client.post(f"/videos/{vid}/turns", json={"text": "Make the offer 30% off"})
    assert job.status_code == 202, job.text
    done = await_job(client, job.json()["job_id"])
    assert done["status"] == "succeeded"
    q = done["result"]["question"]
    assert q["gate"] is True and q["options"][0] == "Go ahead" and q["cost_usd"] == 0.0
    steps = [m for m in client.get(f"/videos/{vid}/messages?after=0").json() if m.get("kind") == "step"]
    assert [s["text"] for s in steps] == ["Read all 1 line", "Thinking"]
    assert steps[0]["data"]["tool"] == "read_transcript" and all(s.get("cost") in (None, 0) for s in steps)

    # Turn 2: the take, copied from the recording, on a ready item; Voltage's recorded words.
    job = client.post(f"/videos/{vid}/turns", json={"text": "Go ahead"})
    done = await_job(client, job.json()["job_id"])
    plan = done["result"]["plan"]
    item = plan["items"][0]
    assert plan["status"] == "done" and item["status"] == "ready" and item["candidate"]["audio"]["container"] == "wav"
    assert item["new_text"] == "Get 30% off today only."
    assert "in a stock voice (Sarah)" in done["result"]["reply"]
    audio = client.get(f"/videos/{vid}/artifacts/{item['candidate']['audio']['sha256']}")
    assert audio.status_code == 200 and len(audio.content) > 1000
    assert client.get(f"/videos/{vid}/usage").json()["spent_usd"] == 0

    # The tour covers one edit; anything more is a sentence, not a job.
    again = client.post(f"/videos/{vid}/turns", json={"text": "Make it 40% off"})
    assert again.status_code == 409 and "one edit" in again.json()["detail"]


def test_not_yet_at_the_gate_leaves_the_plan_waiting(client):
    vid = client.post("/tutorial").json()["video_id"]
    await_job(client, client.post(f"/videos/{vid}/turns", json={"text": "Make the offer 30% off"}).json()["job_id"])
    job = client.post(f"/videos/{vid}/turns", json={"text": "Not yet"})
    assert job.status_code == 202
    done = await_job(client, job.json()["job_id"])
    assert done["result"]["question"] is None and done["result"]["plan"]["status"] == "proposed"
    # A yes afterwards still voices the take.
    done = await_job(client, client.post(f"/videos/{vid}/turns", json={"text": "go"}).json()["job_id"])
    assert done["result"]["plan"]["items"][0]["status"] == "ready"
