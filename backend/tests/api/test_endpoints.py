import time

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg, ingest

PREVIEW = {
    "prompt": 'change "20% off" to "30% off"',
    "start": 0.5, "end": 1.0, "voice_profile_id": "speaker-1",
}

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def upload(client, path, name="ad.mp4", content_type="video/mp4", consent=True):
    with open(path, "rb") as handle:
        return client.post(
            "/projects",
            files={"file": (name, handle, content_type)},
            data={"consent": str(consent).lower()},
        )


@pytest.fixture()
def project(client, sample_video):
    resp = upload(client, sample_video)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def project_without_consent(client, sample_video):
    resp = upload(client, sample_video, consent=False)
    assert resp.status_code == 200, resp.text
    return resp.json()


def start_preview(client, **overrides):
    """Kick off generation; returns the accepted job."""
    resp = client.post("/projects/p1/edits/preview", json={**PREVIEW, **overrides})
    assert resp.status_code == 202, resp.text
    return resp.json()


def await_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


def preview(client, **overrides):
    """Generate and wait, returning the finished candidate."""
    job = await_job(client, start_preview(client, **overrides)["job_id"])
    assert job["status"] == "succeeded", job
    return job["result"]


# ── ingest ───────────────────────────────────────────────────────────────────

def test_upload_returns_id_transcript_and_probed_duration(project):
    assert project["project_id"] == "p1"
    assert project["filename"] == "ad.mp4"
    assert project["transcript"][0]["text"] == "Get"
    # Measured by ffprobe, not supplied by the client.
    assert project["duration"] == pytest.approx(2.3, abs=0.05)
    assert project["media"]["kind"] == "video"
    assert len(project["media"]["sha256"]) == 64


def test_upload_without_a_video_track_is_rejected(client, sample_audio_only):
    resp = upload(client, sample_audio_only, name="voice.wav", content_type="audio/wav")
    assert resp.status_code == 422
    assert "no video track" in resp.json()["detail"]


def test_upload_without_an_audio_track_is_rejected(client, sample_video_without_audio):
    resp = upload(client, sample_video_without_audio, name="silent.mp4")
    assert resp.status_code == 422
    assert "no audio track" in resp.json()["detail"]


def test_health_reports_which_capabilities_are_real(client):
    # The suite blanks both vendor keys, so this process is on the mocks.
    body = client.get("/health").json()
    assert body["transcription"] == "mock"
    assert body["voice"] == "mock"


def test_health_reports_the_voice_label_the_process_selected(client, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "voice_label", "elevenlabs:eleven_multilingual_v2:stock")
    monkeypatch.setattr(main, "transcriber_label", "dry-run")
    body = client.get("/health").json()
    assert body["voice"] == "elevenlabs:eleven_multilingual_v2:stock"
    assert body["transcription"] == "dry-run"


def test_upload_of_a_non_media_file_is_rejected(client, tmp_path):
    junk = tmp_path / "notes.mp4"
    junk.write_bytes(b"this is not a video")
    resp = upload(client, junk)
    assert resp.status_code == 422
    assert "not a video" in resp.json()["detail"]


def test_upload_over_the_length_cap_is_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 1.0)
    long_clip = tmp_path / "long.mp4"
    ffmpeg.generate_solid_video(long_clip, 2.0)

    resp = upload(client, long_clip)
    assert resp.status_code == 422
    assert "limit is 1s" in resp.json()["detail"]


def test_a_rejected_upload_allocates_no_project(client, sample_audio_only):
    upload(client, sample_audio_only, name="voice.wav", content_type="audio/wav")
    # The next good upload still gets p1 — the refusal left no trace.
    assert repo.next_id() == "p1"


# ── consent (design spec §2/§7: non-negotiable, binds before generation) ─────

def test_consent_given_at_upload_is_recorded(project):
    assert project["consent"] is not None
    assert project["consent"]["granted_at"]  # ISO timestamp


def test_uploading_without_consent_is_allowed_but_records_none(project_without_consent):
    # Ingesting and transcribing clones nobody; the gate is on generation.
    assert project_without_consent["consent"] is None
    assert project_without_consent["transcript"]


def test_generation_is_refused_without_consent(client, project_without_consent):
    resp = client.post("/projects/p1/edits/preview", json=PREVIEW)
    assert resp.status_code == 403
    assert "right to edit and clone" in resp.json()["detail"]


def test_no_job_is_created_when_consent_is_missing(client, project_without_consent):
    client.post("/projects/p1/edits/preview", json=PREVIEW)
    # The refusal happens before any work is queued.
    assert client.get("/jobs/j1").status_code == 404


def test_granting_consent_afterwards_unblocks_generation(client, project_without_consent):
    assert client.post("/projects/p1/edits/preview", json=PREVIEW).status_code == 403

    granted = client.post("/projects/p1/consent")
    assert granted.status_code == 200
    assert granted.json()["consent"]["granted_at"]

    assert preview(client)["continuity"]["passed"] is True


def test_re_confirming_consent_does_not_restamp_it(client, project):
    first = client.post("/projects/p1/consent").json()["consent"]["granted_at"]
    second = client.post("/projects/p1/consent").json()["consent"]["granted_at"]
    assert first == second


def test_consent_for_an_unknown_project_is_404(client):
    assert client.post("/projects/nope/consent").status_code == 404


# ── serving ──────────────────────────────────────────────────────────────────

def test_source_media_is_served_back(client, project):
    sha = project["media"]["sha256"]
    resp = client.get(f"/projects/p1/artifacts/{sha}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    assert len(resp.content) > 0


def test_media_supports_range_requests_so_the_player_can_seek(client, project):
    sha = project["media"]["sha256"]
    resp = client.get(f"/projects/p1/artifacts/{sha}", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert len(resp.content) == 100
    assert resp.headers["content-range"].startswith("bytes 0-99/")


def test_unknown_artifact_is_404(client, project):
    assert client.get(f"/projects/p1/artifacts/{'a' * 64}").status_code == 404


def test_artifact_of_an_unknown_project_is_404(client, project):
    sha = project["media"]["sha256"]
    assert client.get(f"/projects/nope/artifacts/{sha}").status_code == 404


@pytest.mark.parametrize("bad", ["../../etc/passwd", "not-hex", "A" * 64, "a" * 63])
def test_malformed_artifact_addresses_are_refused(client, project, bad):
    assert client.get(f"/projects/p1/artifacts/{bad}").status_code == 404


# ── edit lifecycle ───────────────────────────────────────────────────────────

def test_preview_returns_candidate_with_continuity(client, project):
    body = preview(client)
    assert body["plan"]["new_text"] == "30% off"
    assert body["plan"]["selection"] == {"start": 0.4, "end": 1.3}  # snapped
    assert body["continuity"]["passed"] is True


def test_preview_returns_addressable_artifacts_without_leaking_paths(client, project):
    body = preview(client)
    assert body["candidate_id"] == "c1"
    assert body["audio"]["container"] == "wav"
    assert body["frames"]["container"] == "mp4"
    assert len(body["audio"]["sha256"]) == 64
    # The client gets a content address, never a server filesystem path.
    assert "path" not in body["audio"] and "path" not in body["frames"]


def test_candidate_media_is_servable(client, project):
    body = preview(client)
    resp = client.get(f"/projects/p1/artifacts/{body['frames']['sha256']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


def test_each_preview_gets_its_own_candidate_id(client, project):
    assert preview(client)["candidate_id"] == "c1"
    assert preview(client, prompt='change "20% off" to "40% off"')["candidate_id"] == "c2"


def test_preview_unknown_project_is_404(client):
    assert client.post("/projects/nope/edits/preview", json=PREVIEW).status_code == 404


# ── async job model ──────────────────────────────────────────────────────────

def test_preview_accepts_immediately_and_hands_back_a_job(client, project):
    job = start_preview(client)
    assert job["job_id"] == "j1"
    assert job["kind"] == "preview"
    assert job["project_id"] == "p1"
    assert job["status"] in ("queued", "running")
    assert job["result"] is None


def test_polling_a_job_through_to_the_candidate(client, project):
    job = await_job(client, start_preview(client)["job_id"])

    assert job["status"] == "succeeded"
    assert job["progress"] == 1.0
    assert job["step"] == "Ready"
    assert job["error"] is None
    assert job["result"]["candidate_id"] == "c1"
    assert job["result"]["continuity"]["passed"] is True


def test_a_finished_job_stays_readable(client, project):
    job_id = start_preview(client)["job_id"]
    await_job(client, job_id)
    # Polling after completion must keep returning the result, not 404.
    again = client.get(f"/jobs/{job_id}")
    assert again.status_code == 200
    assert again.json()["result"]["candidate_id"] == "c1"


def test_unknown_job_is_404(client):
    assert client.get("/jobs/j99").status_code == 404


def test_concurrent_previews_get_separate_jobs_and_candidates(client, project):
    first = start_preview(client, prompt='change "20% off" to "30% off"')
    second = start_preview(client, prompt='change "20% off" to "50% off"')
    assert first["job_id"] != second["job_id"]

    a = await_job(client, first["job_id"])["result"]
    b = await_job(client, second["job_id"])["result"]
    assert a["candidate_id"] != b["candidate_id"]
    assert a["frames"]["sha256"] != b["frames"]["sha256"]


def test_a_vendor_failure_retries_then_fails_the_job_cleanly(client, project, monkeypatch):
    import app.api.main as main
    from app.adapters.base import VendorError

    class BrokenVoice:
        identity = "mock"

        def cost_of(self, plan):
            return 0

        def synthesize(self, source, plan, transcript=None):
            raise VendorError("vendor is down")

    monkeypatch.setattr(main, "voice", BrokenVoice())
    monkeypatch.setattr(main.runner, "_base_delay", 0.0)  # no real backoff waits

    job = await_job(client, start_preview(client)["job_id"])

    assert job["status"] == "failed"
    assert job["attempts"] == 3          # retried the full allowance
    assert "Try again" in job["error"]
    assert job["result"] is None
    # Nothing half-finished was committed.
    assert client.post("/projects/p1/edits", json={"candidate_id": "c1"}).status_code == 404


def test_the_api_stays_usable_after_a_failed_job(client, project, monkeypatch):
    import app.api.main as main
    from app.adapters.base import VendorError

    class BrokenVoice:
        identity = "mock"

        def cost_of(self, plan):
            return 0

        def synthesize(self, source, plan, transcript=None):
            raise VendorError("down")

    monkeypatch.setattr(main, "voice", BrokenVoice())
    monkeypatch.setattr(main.runner, "_base_delay", 0.0)
    await_job(client, start_preview(client)["job_id"])
    monkeypatch.undo()

    # The worker pool survived; a subsequent preview still works.
    assert preview(client)["continuity"]["passed"] is True


def test_the_candidate_id_survives_the_async_boundary(client, project):
    # The id is allocated on the request thread but the candidate is built on a
    # worker; both must agree, or approval would target the wrong media.
    job = await_job(client, start_preview(client)["job_id"])
    candidate_id = job["result"]["candidate_id"]

    approve = client.post("/projects/p1/edits", json={"candidate_id": candidate_id})
    assert approve.status_code == 200
    assert approve.json()["candidate_id"] == candidate_id


def test_approve_commits_the_previewed_candidate_and_export_shows_it(client, project):
    candidate = preview(client)

    approve = client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})
    assert approve.status_code == 200
    assert approve.json()["edit_id"] == "e1"
    assert approve.json()["candidate_id"] == "c1"

    segments = client.post("/projects/p1/export").json()["segments"]
    assert [s["kind"] for s in segments] == ["original", "edited", "original"]

    # The exported span carries the very artifact the preview showed.
    edited = next(s for s in segments if s["kind"] == "edited")
    assert edited["artifact"]["sha256"] == candidate["frames"]["sha256"]
    assert edited["ref"] == candidate["frames"]["sha256"]


def test_export_originals_point_at_the_uploaded_source(client, project):
    candidate = preview(client)
    client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})

    segments = client.post("/projects/p1/export").json()["segments"]
    originals = [s for s in segments if s["kind"] == "original"]
    assert all(s["artifact"]["sha256"] == project["media"]["sha256"] for s in originals)


def test_approving_one_of_several_candidates_picks_the_right_media(client, project):
    first = preview(client, prompt='change "20% off" to "30% off"')
    second = preview(client, prompt='change "20% off" to "50% off"')
    assert first["frames"]["sha256"] != second["frames"]["sha256"]

    client.post("/projects/p1/edits", json={"candidate_id": second["candidate_id"]})

    segments = client.post("/projects/p1/export").json()["segments"]
    edited = next(s for s in segments if s["kind"] == "edited")
    assert edited["artifact"]["sha256"] == second["frames"]["sha256"]


def test_approve_rejected_when_continuity_fails(client, project):
    candidate = preview(client, voice_profile_id="unknown")
    assert candidate["continuity"]["passed"] is False

    resp = client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "continuity check failed"


def test_a_failing_candidate_can_be_approved_on_purpose_and_is_marked(client, project):
    candidate = preview(client, voice_profile_id="unknown")

    resp = client.post(
        "/projects/p1/edits", json={"candidate_id": candidate["candidate_id"], "override": True},
    )

    assert resp.status_code == 200
    assert resp.json()["overridden"] is True
    import app.api.main as main
    assert main.repo.list_edits("p1")[-1].overridden is True


def test_a_passing_candidate_is_not_marked_overridden(client, project):
    candidate = preview(client)
    resp = client.post(
        "/projects/p1/edits", json={"candidate_id": candidate["candidate_id"], "override": True},
    )
    assert resp.json()["overridden"] is False


def test_approve_unknown_candidate_is_404(client, project):
    assert client.post("/projects/p1/edits", json={"candidate_id": "c99"}).status_code == 404


def test_export_unknown_project_is_404(client):
    assert client.post("/projects/nope/export").status_code == 404


# ── voice budget (Phase 4a) ──────────────────────────────────────────────────

class PricedVoice:
    """The mock voice with a price tag, standing in for a paid vendor."""

    identity = "stock"

    def __init__(self, inner, price):
        self._inner, self._price = inner, price
        self.calls = 0

    def cost_of(self, plan):
        return self._price

    def synthesize(self, source, plan, transcript=None):
        self.calls += 1
        return self._inner.synthesize(source, plan, transcript)


def test_an_edit_the_project_cannot_afford_is_refused_before_any_generation(client, project, monkeypatch):
    # The price is only known once the request has been read (Phase 8), which
    # happens inside the job — so the refusal is the job's, and nothing is
    # generated or retried.
    import app.api.main as main
    from app.budget import VoiceBudget
    voice = PricedVoice(main.voice, price=50)
    monkeypatch.setattr(main, "voice", voice)
    monkeypatch.setattr(main, "budget", VoiceBudget(ceiling=10))

    job = await_job(client, start_preview(client)["job_id"])

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert "10 remain" in job["error"]
    assert voice.calls == 0


def test_an_affordable_paid_edit_goes_ahead_and_is_labelled_stock(client, project, monkeypatch):
    import app.api.main as main
    from app.budget import VoiceBudget
    from app.orchestrator.pipeline import STOCK_VOICE_WARNING
    monkeypatch.setattr(main, "voice", PricedVoice(main.voice, price=5))
    monkeypatch.setattr(main, "budget", VoiceBudget(ceiling=10))

    candidate = preview(client)

    assert STOCK_VOICE_WARNING in candidate["continuity"]["warnings"]


class Unfitted:
    """A voice whose line is `natural` seconds against any selection."""

    identity = "stock"

    def __init__(self, natural):
        self.natural = natural
        self.plans = []

    def cost_of(self, plan):
        return 0

    def synthesize(self, source, plan, transcript=None):
        from app.media.ffmpeg import SpanMismatch
        self.plans.append(plan)
        raise SpanMismatch(natural=self.natural, target=plan.selection.end - plan.selection.start)


def test_a_line_too_long_for_the_selection_becomes_a_question(client, project, monkeypatch):
    import app.api.main as main
    voice = Unfitted(natural=2.0)
    monkeypatch.setattr(main, "voice", voice)

    job = await_job(client, start_preview(client)["job_id"])

    assert job["status"] == "succeeded"
    q = job["result"]
    assert q["type"] == "question"
    assert q["text"] == "30% off" and q["mix"] == "replace"
    assert [o["fit"] for o in q["options"]] == ["stretch"]  # no room to run past the end
    assert "rushed" in q["options"][0]["warning"]
    assert len(voice.plans) == 1


def test_a_line_too_short_offers_start_or_stretch(client, project, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "voice", Unfitted(natural=0.2))

    q = await_job(client, start_preview(client)["job_id"])["result"]

    assert [o["fit"] for o in q["options"]] == ["start", "stretch"]
    assert "silence" in q["options"][0]["label"]
    assert "dragged" in q["options"][1]["warning"]


def test_an_answer_carries_the_choice_and_skips_reading_the_request(client, project, monkeypatch):
    import app.api.main as main
    voice = Unfitted(natural=0.2)
    monkeypatch.setattr(main, "voice", voice)

    job = await_job(client, start_preview(
        client, prompt="anything", text="Thirsty", fit="stretch", mix="layer",
    )["job_id"])

    assert job["status"] == "failed"        # the fake cannot place it either way
    plan = voice.plans[0]
    assert (plan.new_text, plan.fit, plan.mix) == ("Thirsty", "stretch", "layer")


def speechless(monkeypatch, main, transcript):
    """Make the stored project read back with `transcript`."""
    from dataclasses import replace
    real_get = main.repo.get
    monkeypatch.setattr(main.repo, "get", lambda pid: replace(real_get(pid), transcript=transcript))


class Reads:
    """An interpreter returning a fixed Intent, recording what it was given."""

    def __init__(self, intent, tokens=None):
        self.intent = intent
        self.tokens = tokens
        self.seen = []

    def interpret(self, prompt, history, context, meter=None):
        self.seen.append((prompt, history, context))
        if meter is not None and self.tokens:
            meter("claude-opus-5", *self.tokens)
        return self.intent


def test_a_request_the_editor_cannot_do_gets_a_reply(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Intent
    monkeypatch.setattr(main, "interpreter", Reads(Intent("unsupported", reply="Speech only.")))

    job = await_job(client, start_preview(client, prompt="make the background white")["job_id"])

    assert job["status"] == "succeeded"
    assert job["result"] == {"type": "reply", "text": "Speech only."}


def test_the_chat_so_far_reaches_the_interpreter(client, project, monkeypatch):
    # Phase 9a: the server keeps the chat, so history is its record — both
    # sides of earlier turns — not whatever the client sends.
    import app.api.main as main
    from app.domain.models import Intent
    reader = Reads(Intent("unsupported", reply="Speech only."))
    monkeypatch.setattr(main, "interpreter", reader)
    await_job(client, start_preview(client, prompt="make it white")["job_id"])

    reader.intent = Intent("speak", new_text="30% off")
    preview(client, prompt="ok, say 30% off")

    _, history, context = reader.seen[1]
    assert [(t.role, t.text) for t in history] == [
        ("user", "make it white"), ("assistant", "Speech only."),
    ]
    assert context.selected == "20% off"


def test_the_chat_is_kept_with_the_project(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Intent
    monkeypatch.setattr(main, "interpreter", Reads(Intent("unsupported", reply="Speech only.")))
    await_job(client, start_preview(client, prompt="make it white")["job_id"])
    await_job(client, start_preview(client, prompt="x", display="Layer it")["job_id"])

    messages = client.get("/projects/p1").json()["messages"]

    assert messages == [
        {"role": "user", "text": "make it white"}, {"role": "assistant", "text": "Speech only."},
        {"role": "user", "text": "Layer it"}, {"role": "assistant", "text": "Speech only."},
    ]


# ── spend is recorded, and the ceiling holds (Phase 9b) ──────────────────────

def test_claude_calls_are_recorded_with_their_estimated_cost(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Intent
    monkeypatch.setattr(main, "interpreter", Reads(Intent("unsupported", reply="No."), tokens=(1000, 200)))

    await_job(client, start_preview(client, prompt="make it white")["job_id"])

    usage = client.get("/projects/p1/usage").json()
    [line] = usage["lines"]
    assert (line["vendor"], line["what"], line["units"], line["calls"]) == ("anthropic", "intent", 1200, 1)
    assert line["usd"] == pytest.approx(0.01)      # 1000 × $5/M + 200 × $25/M
    assert usage["spent_usd"] == pytest.approx(0.01)


def test_voice_characters_count_toward_spend(client, project, monkeypatch):
    import app.api.main as main
    from app.budget import VoiceBudget
    monkeypatch.setattr(main, "voice", PricedVoice(main.voice, price=0))
    budget = VoiceBudget(ceiling=100, ledger=main.ledger, usd_per_1k=0.30)
    monkeypatch.setattr(main, "budget", budget)
    budget.charge("p1", 40)

    usage = client.get("/projects/p1/usage").json()

    assert usage["voice_characters"] == 40
    assert usage["spent_usd"] == pytest.approx(0.012)


def test_no_new_paid_work_once_the_ceiling_is_reached(client, project, monkeypatch):
    import app.api.main as main
    reader = Reads(None)
    monkeypatch.setattr(main, "interpreter", reader)
    main.ledger.record("p1", "anthropic", "intent", 1, "tokens", main.ledger.ceiling_usd)

    job = await_job(client, start_preview(client)["job_id"])

    assert job["status"] == "failed"
    assert "spending limit" in job["error"]
    assert reader.seen == []          # Claude was never called


# ── projects persist, are listed, reopened and deleted (Phase 9a) ────────────

def test_projects_are_listed_newest_first(client, project, sample_video):
    second = upload(client, sample_video).json()["project_id"]
    listed = client.get("/projects").json()["projects"]
    assert [p["project_id"] for p in listed] == [second, "p1"]
    assert listed[1]["filename"] == "ad.mp4" and listed[1]["edits"] == 0


def test_a_project_reopens_with_its_approved_edits(client, project):
    candidate = preview(client)
    client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})

    reopened = client.get("/projects/p1").json()

    assert reopened["transcript"][1]["text"] == "20%"
    assert [e["new_text"] for e in reopened["edits"]] == ["30% off"]


def test_deleting_a_project_removes_it_and_its_media(client, project):
    import app.api.main as main
    media_dir = main.artifacts.root / "p1"
    assert media_dir.is_dir()

    assert client.delete("/projects/p1").status_code == 204

    assert client.get("/projects/p1").status_code == 404
    assert not media_dir.exists()
    assert client.get("/projects").json()["projects"] == []


def test_someone_elses_project_is_not_found(client, project, monkeypatch):
    import app.api.main as main
    main.app.dependency_overrides[main.current_owner] = lambda: "someone-else"
    try:
        assert client.get("/projects/p1").status_code == 404
        assert client.post("/projects/p1/export").status_code == 404
        assert client.delete("/projects/p1").status_code == 404
        assert client.get("/projects").json()["projects"] == []
    finally:
        main.app.dependency_overrides.clear()
    assert client.get("/projects/p1").status_code == 200


def test_projects_survive_a_restart(tmp_path):
    from app.domain.models import Transcript, Word
    from app.store.db import Database
    from app.store.repository import ProjectRepository
    from tests.factories import make_source
    path = tmp_path / "ave.db"
    first = ProjectRepository(Database(path))
    pid = first.next_id()
    first.create(make_source(project_id=pid), Transcript(words=(Word("hi", 0.0, 0.3),)))
    first.add_message(pid, "user", "hello")

    again = ProjectRepository(Database(path))

    assert again.get(pid).transcript.words[0].text == "hi"
    assert [m.text for m in again.messages(pid)] == ["hello"]
    assert again.next_id() == "p2"   # ids are never reused


def test_an_edit_over_no_speech_asks_how_to_mix(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Intent, Transcript
    reader = Reads(Intent("speak", new_text="Thirsty"))
    monkeypatch.setattr(main, "interpreter", reader)
    speechless(monkeypatch, main, Transcript(words=()))

    q = await_job(client, start_preview(client)["job_id"])["result"]

    assert q["type"] == "question"
    assert [o["mix"] for o in q["options"]] == ["replace", "layer", "concatenate"]


def test_the_mix_named_in_the_request_is_not_asked_about(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Intent, Transcript
    monkeypatch.setattr(main, "interpreter", Reads(Intent("speak", new_text="30% off", mix="layer")))
    speechless(monkeypatch, main, Transcript(words=()))

    candidate = preview(client)

    assert candidate["type"] == "candidate"
    assert candidate["plan"]["mix"] == "layer"


# ── measured continuity over the wire (Phase 6a) ─────────────────────────────

def test_unmeasured_scores_arrive_as_null_with_the_measured_list(client, project, monkeypatch):
    import app.api.main as main
    from app.continuity.engine import Assessment
    from app.domain.models import ContinuityReport

    class Measured:
        def assess(self, source, transcript, plan, audio):
            return Assessment(ContinuityReport(
                voice_match=None, prosody=0.97, audio_integration=0.99, lip_sync=None,
                passed=True, warnings=(), measured=("prosody", "audio_integration"),
            ), audio)

    monkeypatch.setattr(main, "continuity", Measured())
    continuity = preview(client)["continuity"]

    assert continuity["voice_match"] is None and continuity["lip_sync"] is None
    assert continuity["prosody"] == 0.97
    assert continuity["measured"] == ["prosody", "audio_integration"]


def test_the_mock_engine_says_nothing_was_measured(client, project):
    assert preview(client)["continuity"]["measured"] == []


def test_health_reports_the_continuity_engine(client, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "continuity_label", "measured:prosody,audio_integration")
    assert client.get("/health").json()["continuity"] == "measured:prosody,audio_integration"


# ── real render (Phase 7) ────────────────────────────────────────────────────

def test_export_renders_a_real_mp4_you_can_download(client, project):
    candidate = preview(client)
    client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})

    body = client.post("/projects/p1/export").json()
    rendered = body["render"]
    assert rendered["kind"] == "video" and rendered["container"] == "mp4"
    assert rendered["duration"] == pytest.approx(project["duration"], abs=0.05)

    download = client.get(f"/projects/p1/artifacts/{rendered['sha256']}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"


def test_export_with_no_edits_still_renders_a_clean_copy(client, project):
    rendered = client.post("/projects/p1/export").json()["render"]
    assert rendered["duration"] == pytest.approx(project["duration"], abs=0.05)


def test_re_approving_a_span_exports_one_edit_not_two(client, project):
    first = preview(client)
    client.post("/projects/p1/edits", json={"candidate_id": first["candidate_id"]})
    second = preview(client, prompt='change "20% off" to "40% off"')
    client.post("/projects/p1/edits", json={"candidate_id": second["candidate_id"]})

    segments = client.post("/projects/p1/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1
    assert edited[0]["ref"] == second["frames"]["sha256"]


def test_voices_are_listed_with_the_default(client):
    body = client.get("/voices").json()
    assert body["default"] == "mock"
    assert [v["voice_id"] for v in body["voices"]] == ["mock"]


# ── speakers and their voices (Phase 11) ─────────────────────────────────────

def detected(client):
    resp = client.post("/projects/p1/speakers/detect")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_speakers_can_be_detected_for_an_older_project(client, project):
    assert project["speakers"] == []
    body = detected(client)
    assert body["speakers"] == [{"label": "A", "name": "Speaker A", "voice_id": None}]
    assert {st["speaker"] for st in body["statements"]} == {"A"}


def test_a_speaker_can_be_renamed_and_given_a_voice(client, project):
    detected(client)
    resp = client.put("/projects/p1/speakers/A", json={"name": "Shopkeeper", "voice_id": "nPczCjzI2devNBz1zQrb"})
    assert resp.json()["speakers"] == [
        {"label": "A", "name": "Shopkeeper", "voice_id": "nPczCjzI2devNBz1zQrb"}]
    resp = client.put("/projects/p1/speakers/A", json={"clear_voice": True})
    assert resp.json()["speakers"][0]["voice_id"] is None
    assert resp.json()["speakers"][0]["name"] == "Shopkeeper"


def test_an_unknown_speaker_is_404(client, project):
    assert client.put("/projects/p1/speakers/Z", json={"name": "x"}).status_code == 404


def test_a_speakers_line_is_spoken_in_their_voice(client, project):
    detected(client)
    client.put("/projects/p1/speakers/A", json={"voice_id": "nPczCjzI2devNBz1zQrb"})
    candidate = preview(client)             # the selection is A's words
    assert candidate["plan"]["voice_profile_id"] == "nPczCjzI2devNBz1zQrb"


def test_without_a_speaker_voice_the_chats_voice_is_used(client, project):
    detected(client)
    candidate = preview(client, voice_profile_id="EXAVITQu4vr4xnSDxMaL")
    assert candidate["plan"]["voice_profile_id"] == "EXAVITQu4vr4xnSDxMaL"


def test_speaker_settings_survive_reopening(client, project):
    detected(client)
    client.put("/projects/p1/speakers/A", json={"name": "Shopkeeper"})
    reopened = client.get("/projects/p1").json()
    assert reopened["speakers"][0]["name"] == "Shopkeeper"
