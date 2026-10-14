"""A speaker's own voice through the API (Phase 15a). No network, no spend:
the voice is the mock with a clone-capable face."""
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.adapters.mock import MockVoiceAdapter
from app.media import ffmpeg
from app.orchestrator.clones import CloneService
from app.orchestrator.pipeline import STOCK_VOICE_WARNING
from tests.api.test_endpoints import PREVIEW, await_job, start_preview, upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)

CLONE = "C" * 20


class CloningMock(MockVoiceAdapter):
    """The mock voice, claiming to be a stock voice that can make clones."""
    identity = "stock"
    can_clone = True

    def __init__(self, store):
        super().__init__(store)
        self.made: list[str] = []
        self.deleted: list[str] = []
        self.clones: set[str] = set()

    def identity_for(self, plan):
        return "clone" if plan.voice_profile_id in self.clones else "stock"

    def register_clone(self, voice_id):
        self.clones.add(voice_id)

    def create_clone(self, name, reference):
        self.made.append(name)
        self.clones.add(CLONE)
        return CLONE

    def delete_clone(self, voice_id):
        self.deleted.append(voice_id)


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_state():
    main.repo.reset()
    main.jobs.reset()
    yield


@pytest.fixture()
def cloning(monkeypatch):
    def install(min_seconds):
        voice = CloningMock(main.artifacts)
        monkeypatch.setattr(main, "voice", voice)
        monkeypatch.setattr(main, "clones", CloneService(main.repo, main.artifacts, voice, min_seconds=min_seconds))
        return voice
    return install


def warnings_of(client, **overrides):
    job = await_job(client, start_preview(client, **overrides)["job_id"])
    assert job["status"] == "succeeded", job
    return job["result"]["continuity"]["warnings"]


def test_the_first_line_makes_the_clone_and_later_lines_reuse_it(client, sample_video, cloning):
    voice = cloning(min_seconds=1.0)
    assert upload(client, sample_video).status_code == 200
    first = warnings_of(client)
    assert STOCK_VOICE_WARNING not in first                 # the speaker's own voice, not a stock one
    assert voice.made == [f"voltage-p1-{main.repo.WHOLE_CLIP}"]
    assert main.repo.clones("p1") == {main.repo.WHOLE_CLIP: CLONE}

    warnings_of(client)
    assert len(voice.made) == 1                              # reused, never cloned twice


def test_too_little_speech_is_stock_and_says_why(client, sample_video, cloning):
    voice = cloning(min_seconds=10.0)
    assert upload(client, sample_video).status_code == 200
    warnings = warnings_of(client)
    assert any("10 s needed to clone it" in w for w in warnings)
    assert STOCK_VOICE_WARNING not in warnings              # the reason stands in its place
    assert voice.made == []


def test_deleting_the_project_deletes_the_clone_at_the_vendor(client, sample_video, cloning):
    voice = cloning(min_seconds=1.0)
    assert upload(client, sample_video).status_code == 200
    warnings_of(client)
    assert client.delete("/projects/p1").status_code == 204
    assert voice.deleted == [CLONE]


def test_health_says_whether_cloning_is_on(client, cloning):
    cloning(min_seconds=1.0)
    assert client.get("/health").json()["cloning"] == "on"


def test_health_says_off_for_a_voice_that_cannot_clone(client):
    assert client.get("/health").json()["cloning"] == "off"        # the suite is on the mock voice


# ── the room (Phase 15c): stems reach the export only when something is edited ──

def test_an_export_with_an_edit_separates_the_voice_from_the_bed(client, sample_video, monkeypatch):
    asked = []
    monkeypatch.setattr(main.stems_module, "available", lambda: True)
    monkeypatch.setattr(main.stems_module, "separate", lambda wav, out: asked.append(out) or None)
    seen = {}
    real = main.compose
    monkeypatch.setattr(main, "compose", lambda *a, **k: seen.update(stems=k.get("stems", "missing")) or real(*a, **k))

    assert upload(client, sample_video).status_code == 200
    assert client.post("/projects/p1/export").status_code == 200
    assert asked == [] and seen["stems"] is None          # nothing edited: no separation, no cost

    candidate = await_job(client, start_preview(client)["job_id"])["result"]
    assert client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]}).status_code == 200
    assert client.post("/projects/p1/export").status_code == 200
    assert len(asked) == 1 and asked[0].name == "stems"   # kept under the project, once per source
    assert seen["stems"] is None                          # the (faked) separation failed: today's render


def test_stems_can_be_switched_off(client, sample_video, monkeypatch):
    monkeypatch.setattr(main.stems_module, "available", lambda: True)
    from dataclasses import replace
    monkeypatch.setattr(main, "settings", replace(main.settings, stems=False))
    assert main._stems(type("R", (), {"source": None})(), type("M", (), {"segments": ()})()) is None
    assert client.get("/health").json()["room"] == "off"


# ── the mouth (Phase 17): moved at export, only where there is a face, and metered ──

class FakeMouth:
    def __init__(self):
        self.sent = []

    def estimate(self, model, seconds):
        return round(0.06 * seconds, 4)

    def move_mouth(self, clip, audio, dest, *, model, options=None):
        from tests.render.test_mouth import solid
        self.sent.append((model, ffmpeg.duration_of(clip)))
        solid(dest, "red", ffmpeg.duration_of(clip))
        return dest, {"status": "COMPLETED"}


def test_an_export_moves_the_mouth_where_there_is_a_face_and_meters_it(client, sample_video, monkeypatch):
    from app.media import faces
    fake = FakeMouth()
    monkeypatch.setattr(main, "mouth_client", fake)
    monkeypatch.setattr(faces, "stretches", lambda video, a, b, cuts=(), **k: [faces.Stretch(a, min(b, a + 0.5), 1)])
    assert upload(client, sample_video).status_code == 200
    candidate = await_job(client, start_preview(client)["job_id"])["result"]
    assert client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]}).status_code == 200

    out = client.post("/projects/p1/export").json()
    assert out["mouth"]["model"] == "lipsync-2" and len(out["mouth"]["moved"]) == 1
    assert out["mouth"]["seconds"] == pytest.approx(0.5, abs=0.05) and out["mouth"]["usd"] > 0
    assert len(fake.sent) == 1
    lines = {(l.vendor, l.what) for l in main.ledger.lines("p1")}
    assert ("sync", "mouth (lipsync-2)") in lines                       # on the project's meter

    again = client.post("/projects/p1/export").json()                    # the same take: nothing more to pay
    assert len(fake.sent) == 1 and again["mouth"]["usd"] == 0 and again["mouth"]["moved"][0]["cached"]


def test_without_a_lip_sync_key_the_export_is_exactly_as_before(client, sample_video):
    assert main.mouth_client is None
    assert upload(client, sample_video).status_code == 200
    assert client.post("/projects/p1/export").json()["mouth"] is None
    assert client.get("/health").json()["lipsync"] == "mock"
