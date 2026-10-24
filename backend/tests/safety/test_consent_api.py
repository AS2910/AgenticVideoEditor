"""Run 4 item 2 through the API: with `voices.cloning_verified` on, the
read-aloud step is the real gate (a phrase, the words, the voice), its
evidence is stored, a borderline check waits in the admin queue (approve or
reject with a reason, audited, the owner told), and a speaker is cloned only
once their video's check has passed. Whisper and WavLM are injected fakes:
the transcript of a test recording is the known text."""
import io

import pytest

import app.api.main as main
from app import safety_api
from app.api.main import database, flags, repo
from app.domain.models import Selection
from app.media import ffmpeg
from app.orchestrator.clones import VoiceChoice
from tests.safety.conftest import PHRASE, _read, _row

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


def test_the_phrase_is_read_checked_stored_and_cited(client, video, sample_video):
    start = client.post("/videos/p1/liveness", json={"speaker": "A"}).json()
    assert start["sentence"] == PHRASE and start["verified"] and not start["test_mode"] and start["status"] == "waiting"
    assert start["min_seconds"] == 4.0 and start["attempt_id"].startswith("cv_")
    checked = _read(client, start["attempt_id"], sample_video).json()
    assert checked == {"attempt_id": start["attempt_id"], "status": "passed", "reason": "The words and the voice match the speaker in the video.",
                       "tip": "", "test_mode": False, "verified": True}
    row = _row(start["attempt_id"])
    assert row["method"] == "verified" and row["sentence"] == PHRASE and row["heard"] == PHRASE and row["wer"] == 0.0
    assert row["similarity"] == 0.95 and row["seconds"] == 5.0 and row["rule"] == "voice" and row["audio_sha"]
    assert row["asr_model"] == "openai:whisper-1" and row["speaker_model"] == "microsoft/wavlm-base-plus-sv"
    assert row["pass_at"] == 0.92 and row["review_from"] == 0.84 and row["expires_at"] > row["created_at"] and row["checked_at"]
    assert _read(client, start["attempt_id"], sample_video).status_code == 409          # single use
    ok = client.post("/videos/p1/consent", json={"liveness_id": start["attempt_id"]})
    assert ok.status_code == 200 and ok.json()["consent_granted_at"]


def test_a_stand_in_check_does_not_count_once_the_flag_is_on(client, video, sample_video):
    flags.set("voices.cloning_verified", "local", False)
    old = client.post("/videos/p1/liveness", json={}).json()
    assert "My code is" in old["sentence"] and not old["verified"]
    assert _read(client, old["attempt_id"], sample_video).json()["status"] == "passed"
    flags.set("voices.cloning_verified", "local", True)
    refused = client.post("/videos/p1/consent", json={"liveness_id": old["attempt_id"]})
    assert refused.status_code == 422 and "phrase" in refused.json()["detail"]


def test_each_rule_says_why_and_what_to_try(client, video, sample_video, reset_state):
    fakes = reset_state
    fakes.seconds = 2.5
    first = client.post("/videos/p1/liveness", json={}).json()
    short = _read(client, first["attempt_id"], sample_video).json()
    assert short["status"] == "failed" and "at least 4 s" in short["reason"] and short["tip"]
    fakes.seconds, fakes.heard = 5.0, "purple kettle something else entirely"
    words = _read(client, client.post("/videos/p1/liveness", json={}).json()["attempt_id"], sample_video).json()
    assert words["status"] == "failed" and "did not match the phrase" in words["reason"] and "Read every word" in words["tip"]
    fakes.heard, fakes.sim = PHRASE, 0.5
    voice = _read(client, client.post("/videos/p1/liveness", json={}).json()["attempt_id"], sample_video).json()
    assert voice["status"] == "failed" and "does not match the speaker" in voice["reason"] and voice["tip"]
    assert client.post("/videos/p1/consent", json={"liveness_id": first["attempt_id"]}).status_code == 422


def test_an_old_phrase_is_spent(client, video, sample_video):
    start = client.post("/videos/p1/liveness", json={}).json()
    with database.tx() as c:
        c.execute("UPDATE liveness_attempts SET expires_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (start["attempt_id"],))
    late = _read(client, start["attempt_id"], sample_video)
    assert late.status_code == 410 and "expired" in late.json()["detail"]
    assert _row(start["attempt_id"])["status"] == "expired"


def test_a_speaker_is_cloned_only_after_their_check_passes(client, video, sample_video, monkeypatch):
    resolved = []
    monkeypatch.setattr(main.clones, "resolve", lambda *a: resolved.append(a[0]) or VoiceChoice("clone-1", cloned=True))
    record = repo.get("p1")
    before = main._voice_for("p1", record, Selection(0.4, 1.3), "mock", speaker="A")
    assert before.voice_id == "mock" and before.notes == ("Stock voice: the speaker's consent check has not passed yet.",)
    assert main.cloning_open("local")
    start = client.post("/videos/p1/liveness", json={}).json()
    _read(client, start["attempt_id"], sample_video)
    after = main._voice_for("p1", record, Selection(0.4, 1.3), "mock", speaker="A")
    assert after.cloned and resolved == ["p1"]
    # Withdrawing consent spends the check: the next consent reads a new phrase.
    client.post("/videos/p1/consent/withdraw")
    assert _row(start["attempt_id"])["status"] == "withdrawn"
    assert not main._voice_for("p1", record, Selection(0.4, 1.3), "mock", speaker="A").cloned
    assert client.post("/videos/p1/liveness", json={}).json()["attempt_id"] != start["attempt_id"]


def test_with_both_voice_flags_off_cloning_stays_closed(video, monkeypatch):
    flags.set("voices.cloning_verified", "local", False)
    assert not main.cloning_open("local")
    choice = main._voice_for("p1", repo.get("p1"), Selection(0.4, 1.3), "mock", speaker="A")
    assert choice.notes == ("Stock voice: voice cloning is not open yet.",)


def test_a_too_long_recording_is_refused(client, video):
    start = client.post("/videos/p1/liveness", json={}).json()
    big = io.BytesIO(b"\x1a\x45\xdf\xa3" + b"\0" * (safety_api.MAX_RECORDING_BYTES + 10))
    assert client.post(f"/videos/p1/liveness/{start['attempt_id']}", files={"file": ("x.webm", big, "audio/webm")}).status_code in (413, 422)
