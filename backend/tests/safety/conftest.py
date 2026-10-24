"""Run 4 item 2: shared fixtures for the consent gate's API tests. Whisper and
WavLM are fakes set per test (`reset_state` yields them): the transcript of a
test recording is the known text, and no model or vendor is called."""
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import safety_api
from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from app.safety.consent import ConsentVerifier

PHRASE = "Purple kettle river tiger window salad pencil morning garden quiet."
H = {"X-Requested-With": "voltage"}


class Fakes:
    """What Whisper hears and what WavLM scores, set per test."""
    heard: str | None = PHRASE
    sim: float | None = 0.95
    seconds: float = 5.0


@pytest.fixture(autouse=True)
def reset_state(monkeypatch, tmp_path):
    repo.reset()
    jobs.reset()
    flags.set("golive.g6", "local", True)
    flags.set("voices.cloning_verified", "local", True)
    flags.set("voices.cloning", "local", False)
    fakes = Fakes()
    monkeypatch.setattr(safety_api.consent_mod, "phrase", lambda rng=None: PHRASE)
    monkeypatch.setattr(main, "consent_verifier", ConsentVerifier(
        transcribe=lambda p, vid: fakes.heard, similarity=lambda ref, rec: fakes.sim, seconds_of=lambda p: fakes.seconds,
        asr_model="openai:whisper-1", speaker_model="microsoft/wavlm-base-plus-sv"))
    source = tmp_path / "speaker.wav"
    ffmpeg.generate_silence(source, 3.0)
    monkeypatch.setattr(main, "consent_reference", lambda vid, record, speaker: source)
    yield fakes
    for flag in ("golive.g6", "voices.cloning_verified", "voices.cloning"):
        flags.clear(flag, "local")


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


def _read(client, attempt, sample_video, name="me.mp4"):
    with open(sample_video, "rb") as f:
        return client.post(f"/videos/p1/liveness/{attempt}", files={"file": (name, f, "video/mp4")})


def _row(attempt):
    with database.tx() as c:
        return dict(c.execute("SELECT * FROM liveness_attempts WHERE id = ?", (attempt,)).fetchone())


