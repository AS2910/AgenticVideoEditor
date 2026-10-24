"""Run 4 item 2: the admin review queue for borderline consent checks:
listed with the phrase, what was heard and the scores, the recording and the
speaker's speech to compare; approve or reject with a reason, audited, the
owner told; admins only. Fixtures (fake Whisper and WavLM) are in
conftest.py."""
import pytest

from app import admin, analytics_api
from app.api.main import database
from app.media import ffmpeg
from tests.safety.conftest import PHRASE, H, _read

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


def test_a_borderline_voice_waits_for_a_person_who_approves_it(client, video, sample_video, reset_state):
    reset_state.sim = 0.88
    start = client.post("/videos/p1/liveness", json={}).json()
    checked = _read(client, start["attempt_id"], sample_video).json()
    assert checked["status"] == "review" and "a person will listen" in checked["reason"]
    bell = client.get("/me/notifications").json()["items"]
    assert bell[0]["kind"] == "consent_review" and bell[0]["link"] == "#admin"
    # Opening the step again shows the same check, not a new phrase; `fresh` starts over.
    again = client.post("/videos/p1/liveness", json={}).json()
    assert again["attempt_id"] == start["attempt_id"] and again["status"] == "review"
    assert client.post("/videos/p1/consent", json={"liveness_id": start["attempt_id"]}).status_code == 422

    queue = client.get("/admin/consent-reviews").json()
    assert queue["waiting"] == 1 and [i["id"] for i in queue["items"]] == [start["attempt_id"]]
    item = queue["items"][0]
    assert item["sentence"] == PHRASE and item["heard"] == PHRASE and item["similarity"] == 0.88 and item["has_recording"]
    assert client.get(f"/admin/consent-reviews/{start['attempt_id']}/recording").status_code == 200
    assert client.get(f"/admin/consent-reviews/{start['attempt_id']}/source").headers["content-type"] == "audio/wav"

    assert client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "approve", "reason": ""}, headers=H).status_code == 422
    assert client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "maybe", "reason": "listened"}, headers=H).status_code == 422
    done = client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "approve", "reason": "Same voice, quiet room"}, headers=H)
    assert done.status_code == 200 and done.json()["status"] == "passed" and done.json()["reviewed_by"] == "local"
    assert done.json()["review_reason"] == "Same voice, quiet room" and done.json()["reviewed_at"]
    assert client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "reject", "reason": "changed my mind"},
                       headers=H).status_code == 409                                          # decided once
    [audit] = [r for r in admin.recent_audit(database, target="local") if r["action"] == "consent_approve"][:1]
    assert audit["reason"] == "Same voice, quiet room" and audit["details"]["attempt_id"] == start["attempt_id"]
    assert audit["details"]["similarity"] == 0.88 and audit["details"]["video_id"] == "p1"
    told = client.get("/me/notifications").json()["items"][0]
    assert told["kind"] == "consent_decided" and told["title"] == "Your consent recording was approved."
    assert client.get("/admin/consent-reviews").json()["waiting"] == 0
    assert [i["id"] for i in client.get("/admin/consent-reviews", params={"status": "decided"}).json()["items"]] == [start["attempt_id"]]
    assert client.post("/videos/p1/consent", json={"liveness_id": start["attempt_id"]}).status_code == 200


def test_a_rejected_check_does_not_pass_and_a_new_phrase_can_be_read(client, video, sample_video, reset_state):
    reset_state.sim = None                                         # not measured: a person listens
    start = client.post("/videos/p1/liveness", json={}).json()
    assert _read(client, start["attempt_id"], sample_video).json()["status"] == "review"
    fresh = client.post("/videos/p1/liveness", json={"fresh": True}).json()
    assert fresh["attempt_id"] != start["attempt_id"] and fresh["status"] == "waiting"
    out = client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "reject", "reason": "Two voices in it"}, headers=H).json()
    assert out["status"] == "failed" and "could not confirm" in out["reason"]
    assert any(r["action"] == "consent_reject" for r in admin.recent_audit(database, target="local"))
    assert client.get("/me/notifications").json()["items"][0]["title"] == "Your consent recording was not approved."
    assert client.post("/videos/p1/consent", json={"liveness_id": start["attempt_id"]}).status_code == 422


def test_only_admins_see_the_queue(client, video, sample_video, reset_state, monkeypatch):
    reset_state.sim = 0.88
    start = client.post("/videos/p1/liveness", json={}).json()
    _read(client, start["attempt_id"], sample_video)
    monkeypatch.setattr(analytics_api, "is_admin", lambda user: False)
    assert client.get("/admin/consent-reviews").status_code == 404
    assert client.get(f"/admin/consent-reviews/{start['attempt_id']}/recording").status_code == 404
    assert client.post(f"/admin/consent-reviews/{start['attempt_id']}", json={"decision": "approve", "reason": "fine by me"},
                       headers=H).status_code == 404
