import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.mock import MockVoiceAdapter
from app.api.main import app, repo, jobs
from app.media import ffmpeg, ingest

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


def await_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


# ── a take, the way Voltage makes one (Phase 20d) ─────────────────────────────
#
# There is no request that previews an edit from a selection any more: a take
# is made by the agent's `synthesize_take`, which calls `main._generate`. Tests
# about candidates, approval, export, continuity and spend call `_generate`
# the same way; tests about the chat and the thread run a scripted turn.

# The words "20% off" in the canned clip, as the agent would name them.
WORDS = (0.4, 1.3)


def generate(text="30% off", start=WORDS[0], end=WORDS[1], voice_id="mock", fit=None, mix="replace",
             report=None, project_id="p1", **kw):
    """One take of `text` over `start`–`end`, straight through `main._generate`
    (what the agent's `synthesize_take` calls), saved as a candidate. Returns
    the candidate as the API shows it."""
    import app.api.main as main
    from app.domain.models import Selection
    record = main.repo.get(project_id)
    candidate = main._generate(
        project_id, record, main.repo.next_candidate_id(project_id), Selection(start, end), text, voice_id,
        fit, mix, report or (lambda progress, step: None), **kw,
    )
    return main._candidate_dict(candidate)


def _agent_on(monkeypatch, main, responses):
    """Voltage on, answering with a scripted Claude. Returns the scripted client."""
    from dataclasses import replace
    from app.agent.loop import Agent
    from tests.agent.conftest import ScriptedClient
    monkeypatch.setattr(main, "settings", replace(main.settings, agent=True, anthropic_api_key="k"))
    client = ScriptedClient(responses)
    monkeypatch.setattr(main, "_agent_instance", Agent(client))
    return client


def take(_id="c", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None, direction="",
         mix="layer", **more):
    """The agent's `synthesize_take` call, every argument spelled out as the
    model sends them. `line=1` replaces the canned clip's one line; `line=None`
    with `start`/`end` places an added line."""
    from tests.agent.conftest import use
    return use("synthesize_take", _id, text=text, voice_id=voice_id, line=line, start=start, end=end,
               direction=direction, mix=mix, item_id="", model="default", stability=None, style=None, speed=None,
               similarity=None, fit="fit", picture="default", **more)


def send(client, text, approve=False, project_id="p1"):
    """One turn, waited for; returns the job's result."""
    resp = client.post(f"/projects/{project_id}/turns", json={"text": text, "approve": approve})
    assert resp.status_code == 202, resp.text
    job = await_job(client, resp.json()["job_id"])
    assert job["status"] == "succeeded", job
    return job["result"]


def turn(client, monkeypatch, responses, text="make it 30% off", autonomy="draft"):
    """A scripted turn of Voltage under `autonomy`; returns the job's result."""
    import app.api.main as main
    client.put("/projects/p1/settings", json={"autonomy": autonomy})
    _agent_on(monkeypatch, main, responses)
    return send(client, text)


def voiced(client, monkeypatch, text="Get 30% off today only.", **kw):
    """A turn under Just do it that voices line 1 as `text` and says so."""
    from tests.agent.conftest import reply, text as said
    return turn(client, monkeypatch, [reply(take(text=text, **kw), stop="tool_use"), reply(said("Hear it."))])


def speechless(monkeypatch, main, transcript):
    """Make the stored project read back with `transcript`."""
    from dataclasses import replace
    real_get = main.repo.get
    monkeypatch.setattr(main.repo, "get", lambda pid: replace(real_get(pid), transcript=transcript))


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
    assert body["planner"] == "none" and "intent" not in body


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


def test_generation_is_refused_without_consent(client, project_without_consent, monkeypatch):
    # Under Just do it a turn may voice the speaker, so it is refused before it starts.
    import app.api.main as main
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [])
    resp = client.post("/projects/p1/turns", json={"text": "make it 30% off"})
    assert resp.status_code == 403
    assert "right to edit and clone" in resp.json()["detail"]
    assert scripted.calls == []


def test_no_job_is_created_when_consent_is_missing(client, project_without_consent, monkeypatch):
    import app.api.main as main
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [])
    client.post("/projects/p1/turns", json={"text": "make it 30% off"})
    # The refusal happens before any work is queued.
    assert client.get("/jobs/j1").status_code == 404


def test_granting_consent_afterwards_unblocks_generation(client, project_without_consent, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(take(), stop="tool_use"), reply(said("Hear it."))])
    assert client.post("/projects/p1/turns", json={"text": "make it 30% off"}).status_code == 403

    granted = client.post("/projects/p1/consent")
    assert granted.status_code == 200
    assert granted.json()["consent"]["granted_at"]

    [item] = send(client, "make it 30% off")["plan"]["items"]
    assert item["status"] == "ready" and item["candidate"]["continuity"]["passed"] is True


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
    body = generate()
    assert body["plan"]["new_text"] == "30% off"
    assert body["plan"]["selection"] == {"start": 0.4, "end": 1.3}
    assert body["continuity"]["passed"] is True


def test_preview_returns_addressable_artifacts_without_leaking_paths(client, project):
    body = generate()
    assert body["candidate_id"] == "c1"
    assert body["audio"]["container"] == "wav"
    assert body["frames"]["container"] == "mp4"
    assert len(body["audio"]["sha256"]) == 64
    # The client gets a content address, never a server filesystem path.
    assert "path" not in body["audio"] and "path" not in body["frames"]


def test_candidate_media_is_servable(client, project):
    body = generate()
    resp = client.get(f"/projects/p1/artifacts/{body['frames']['sha256']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


def test_each_take_gets_its_own_candidate_id(client, project):
    assert generate()["candidate_id"] == "c1"
    assert generate(text="40% off")["candidate_id"] == "c2"


def test_a_turn_on_an_unknown_project_is_404(client, monkeypatch):
    import app.api.main as main
    _agent_on(monkeypatch, main, [])
    assert client.post("/projects/nope/turns", json={"text": "hi"}).status_code == 404


# ── async job model ──────────────────────────────────────────────────────────

def test_a_turn_accepts_immediately_and_hands_back_a_job(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    _agent_on(monkeypatch, main, [reply(said("Nothing to do."))])
    resp = client.post("/projects/p1/turns", json={"text": "hi"})
    assert resp.status_code == 202
    job = resp.json()
    assert job["job_id"] == "j1"
    assert job["kind"] == "turn"
    assert job["project_id"] == "p1"
    assert job["status"] in ("queued", "running")
    assert job["result"] is None
    await_job(client, job["job_id"])


def test_polling_a_job_through_to_the_candidate(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(take(), stop="tool_use"), reply(said("Hear it."))])
    job = await_job(client, client.post("/projects/p1/turns", json={"text": "make it 30% off"}).json()["job_id"])

    assert job["status"] == "succeeded"
    assert job["progress"] == 1.0
    assert job["step"] == "Ready"
    assert job["error"] is None
    assert job["result"]["type"] == "turn"
    [item] = job["result"]["plan"]["items"]
    assert item["candidate"]["candidate_id"] == "c1"
    assert item["candidate"]["continuity"]["passed"] is True


def test_a_finished_job_stays_readable(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    _agent_on(monkeypatch, main, [reply(said("Nothing to do."))])
    job_id = client.post("/projects/p1/turns", json={"text": "hi"}).json()["job_id"]
    await_job(client, job_id)
    # Polling after completion must keep returning the result, not 404.
    again = client.get(f"/jobs/{job_id}")
    assert again.status_code == 200
    assert again.json()["result"]["reply"] == "Nothing to do."


def test_unknown_job_is_404(client):
    assert client.get("/jobs/j99").status_code == 404


def test_two_takes_in_one_turn_get_separate_candidates_and_media(client, project, monkeypatch):
    from tests.agent.conftest import reply, text as said
    done = turn(client, monkeypatch, [
        reply(take("c", text="Get 30% off today only."), take("d", text="Get 50% off today only."), stop="tool_use"),
        reply(said("Two to hear.")),
    ])
    a, b = [i["candidate"] for i in done["plan"]["items"]]
    assert a["candidate_id"] != b["candidate_id"]
    assert a["frames"]["sha256"] != b["frames"]["sha256"]


class Broken(MockVoiceAdapter):
    """The mock voice, but the vendor is down."""

    def __init__(self, store, message="vendor is down"):
        super().__init__(store)
        self.message = message

    def synthesize(self, source, plan, transcript=None):
        from app.adapters.base import VendorError
        raise VendorError(self.message)


def test_a_vendor_failure_fails_the_take_not_the_turn_and_commits_nothing(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    monkeypatch.setattr(main, "voice", Broken(main.artifacts, "ElevenLabs is unavailable right now (503)."))

    done = turn(client, monkeypatch, [reply(take(), stop="tool_use"), reply(said("ElevenLabs is down; I'll try again when you say."))])

    [item] = done["plan"]["items"]
    assert item["status"] == "failed" and "ElevenLabs is unavailable" in item["error"]
    assert done["plan"]["status"] == "done" and done["reply"].startswith("ElevenLabs is down")
    steps = [m["text"] for m in client.get("/projects/p1/messages").json() if m["kind"] == "step"]
    assert any(s.startswith("Could not voice") for s in steps)
    # Nothing half-finished was committed.
    assert client.post("/projects/p1/edits", json={"candidate_id": "c1"}).status_code == 404


def test_the_api_stays_usable_after_a_failed_take(client, project, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "voice", Broken(main.artifacts))
    assert voiced(client, monkeypatch)["plan"]["items"][0]["status"] == "failed"
    monkeypatch.undo()

    # The worker pool survived; the next take works.
    assert generate()["continuity"]["passed"] is True


def test_the_candidate_a_turn_reports_is_the_one_approval_commits(client, project, monkeypatch):
    # The take is made on a worker; the id it reports and the one approval
    # targets must agree, or approval would commit the wrong media.
    candidate_id = voiced(client, monkeypatch)["plan"]["items"][0]["candidate"]["candidate_id"]

    approve = client.post("/projects/p1/edits", json={"candidate_id": candidate_id})
    assert approve.status_code == 200
    assert approve.json()["candidate_id"] == candidate_id


def test_approve_commits_the_previewed_candidate_and_export_shows_it(client, project):
    candidate = generate()

    approve = client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})
    assert approve.status_code == 200
    assert approve.json()["edit_id"] == "e1"
    assert approve.json()["candidate_id"] == "c1"

    segments = client.post("/projects/p1/export").json()["segments"]
    assert [s["kind"] for s in segments] == ["original", "edited", "original"]

    # The exported span carries the very artifact the user heard.
    edited = next(s for s in segments if s["kind"] == "edited")
    assert edited["artifact"]["sha256"] == candidate["frames"]["sha256"]
    assert edited["ref"] == candidate["frames"]["sha256"]


def test_export_originals_point_at_the_uploaded_source(client, project):
    candidate = generate()
    client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})

    segments = client.post("/projects/p1/export").json()["segments"]
    originals = [s for s in segments if s["kind"] == "original"]
    assert all(s["artifact"]["sha256"] == project["media"]["sha256"] for s in originals)


def test_approving_one_of_several_candidates_picks_the_right_media(client, project):
    first = generate(text="30% off")
    second = generate(text="50% off")
    assert first["frames"]["sha256"] != second["frames"]["sha256"]

    client.post("/projects/p1/edits", json={"candidate_id": second["candidate_id"]})

    segments = client.post("/projects/p1/export").json()["segments"]
    edited = next(s for s in segments if s["kind"] == "edited")
    assert edited["artifact"]["sha256"] == second["frames"]["sha256"]


def test_approve_rejected_when_continuity_fails(client, project):
    candidate = generate(voice_id="unknown")
    assert candidate["continuity"]["passed"] is False

    resp = client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "continuity check failed"


def test_a_failing_candidate_can_be_approved_on_purpose_and_is_marked(client, project):
    candidate = generate(voice_id="unknown")

    resp = client.post(
        "/projects/p1/edits", json={"candidate_id": candidate["candidate_id"], "override": True},
    )

    assert resp.status_code == 200
    assert resp.json()["overridden"] is True
    import app.api.main as main
    assert main.repo.list_edits("p1")[-1].overridden is True


def test_a_passing_candidate_is_not_marked_overridden(client, project):
    candidate = generate()
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
    import app.api.main as main
    from app.budget import BudgetExceeded, VoiceBudget
    voice = PricedVoice(main.voice, price=50)
    monkeypatch.setattr(main, "voice", voice)
    monkeypatch.setattr(main, "budget", VoiceBudget(ceiling=10))

    with pytest.raises(BudgetExceeded) as refused:
        generate()

    assert "10 remain" in str(refused.value)
    assert voice.calls == 0
    assert main.repo.get_candidate("p1", "c1") is None      # nothing was made or saved


def test_an_affordable_paid_edit_goes_ahead_and_is_labelled_stock(client, project, monkeypatch):
    import app.api.main as main
    from app.budget import VoiceBudget
    from app.orchestrator.pipeline import STOCK_VOICE_WARNING
    monkeypatch.setattr(main, "voice", PricedVoice(main.voice, price=5))
    monkeypatch.setattr(main, "budget", VoiceBudget(ceiling=10))

    candidate = generate()

    assert STOCK_VOICE_WARNING in candidate["continuity"]["warnings"]


class Unfitted(MockVoiceAdapter):
    """A voice whose line is `natural` seconds against any selection."""

    identity = "stock"

    def __init__(self, store, natural):
        super().__init__(store)
        self.natural = natural
        self.plans = []

    def synthesize(self, source, plan, transcript=None):
        from app.media.ffmpeg import SpanMismatch
        self.plans.append(plan)
        raise SpanMismatch(natural=self.natural, target=plan.selection.end - plan.selection.start)


def test_a_take_that_does_not_fit_is_raised_to_voltage_not_asked_about(client, project, monkeypatch):
    """20d: a line that runs long is no longer a question for the user.
    `_generate` raises SpanMismatch to its caller, the agent, which hears why
    and decides (a shorter wording, another placement)."""
    import app.api.main as main
    from app.media.ffmpeg import SpanMismatch
    from tests.agent.conftest import reply, text as said
    voice = Unfitted(main.artifacts, natural=2.0)
    monkeypatch.setattr(main, "voice", voice)

    with pytest.raises(SpanMismatch):
        generate()
    assert [p.fit for p in voice.plans] == [None]           # one take, no placement guessed
    assert main.repo.get_candidate("p1", "c1") is None

    done = turn(client, monkeypatch, [reply(take(), stop="tool_use"), reply(said("That runs long; I'll shorten it."))])
    [item] = done["plan"]["items"]
    assert item["status"] == "failed" and item["error"]
    assert done["reply"] == "That runs long; I'll shorten it."


def test_the_chat_is_kept_with_the_project(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    _agent_on(monkeypatch, main, [reply(said("Speech only.")), reply(said("Layered."))])
    send(client, "make it white")
    send(client, "Layer it")

    messages = [m for m in client.get("/projects/p1").json()["messages"] if m["kind"] == "say"]   # the steps aside

    assert [{"role": m["role"], "text": m["text"]} for m in messages] == [
        {"role": "user", "text": "make it white"}, {"role": "assistant", "text": "Speech only."},
        {"role": "user", "text": "Layer it"}, {"role": "assistant", "text": "Layered."},
    ]


# ── spend is recorded, and the ceiling holds (Phase 9b) ──────────────────────

def test_claude_calls_are_recorded_with_their_estimated_cost(client, project, monkeypatch):
    import app.api.main as main
    from app.usage import claude_usd
    from tests.agent.conftest import reply, text as said
    turn(client, monkeypatch, [reply(said("Nothing to change."))], text="hi")

    usage = client.get("/projects/p1/usage").json()
    [line] = usage["lines"]
    assert (line["vendor"], line["what"], line["units"], line["calls"]) == ("anthropic", "agent", 120, 1)
    assert line["usd"] == pytest.approx(claude_usd(main._agent_instance.model, 100, 20))   # the scripted reply's tokens
    assert usage["spent_usd"] == pytest.approx(line["usd"])


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
    scripted = _agent_on(monkeypatch, main, [])
    main.ledger.record("p1", "anthropic", "agent", 1, "tokens", main.ledger.ceiling_usd)

    result = send(client, "make it 30% off")

    assert "spending limit" in result["reply"]
    assert result["plan"]["status"] == "proposed"
    assert scripted.calls == []          # Claude was never called


# ── projects persist, are listed, reopened and deleted (Phase 9a) ────────────

def test_projects_are_listed_newest_first(client, project, sample_video):
    second = upload(client, sample_video).json()["project_id"]
    listed = client.get("/projects").json()["projects"]
    assert [p["project_id"] for p in listed] == [second, "p1"]
    assert listed[1]["filename"] == "ad.mp4" and listed[1]["edits"] == 0


def test_a_project_reopens_with_its_approved_edits(client, project):
    candidate = generate()
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
    continuity = generate()["continuity"]

    assert continuity["voice_match"] is None and continuity["lip_sync"] is None
    assert continuity["prosody"] == 0.97
    assert continuity["measured"] == ["prosody", "audio_integration"]


def test_the_mock_engine_says_nothing_was_measured(client, project):
    assert generate()["continuity"]["measured"] == []


def test_health_reports_the_continuity_engine(client, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "continuity_label", "measured:prosody,audio_integration")
    assert client.get("/health").json()["continuity"] == "measured:prosody,audio_integration"


# ── real render (Phase 7) ────────────────────────────────────────────────────

def test_export_renders_a_real_mp4_you_can_download(client, project):
    candidate = generate()
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
    first = generate()
    client.post("/projects/p1/edits", json={"candidate_id": first["candidate_id"]})
    second = generate(text="40% off")
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


def test_a_speakers_line_is_spoken_in_their_voice(client, project, monkeypatch):
    detected(client)
    client.put("/projects/p1/speakers/A", json={"voice_id": "nPczCjzI2devNBz1zQrb"})
    result = voiced(client, monkeypatch, voice_id="")      # line 1 is A's; an empty voice is their own
    assert result["plan"]["items"][0]["candidate"]["plan"]["voice_profile_id"] == "nPczCjzI2devNBz1zQrb"


def test_without_a_speaker_voice_the_default_voice_is_used(client, project, monkeypatch):
    detected(client)
    result = voiced(client, monkeypatch, voice_id="")      # nothing picked for A, and the mock cannot clone
    assert result["plan"]["items"][0]["candidate"]["plan"]["voice_profile_id"] == "mock"


def test_speaker_settings_survive_reopening(client, project):
    detected(client)
    client.put("/projects/p1/speakers/A", json={"name": "Shopkeeper"})
    reopened = client.get("/projects/p1").json()
    assert reopened["speakers"][0]["name"] == "Shopkeeper"


# ── Phase 12: Revert, project settings ───────────────────────────────────────

def test_a_reverted_edit_is_marked_skipped_by_the_render_and_not_counted(client, project):
    candidate = generate()
    client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]})
    assert client.get("/projects").json()["projects"][0]["edits"] == 1

    resp = client.post("/projects/p1/edits/e1/revert")

    assert resp.status_code == 200 and resp.json() == {"edit_id": "e1", "reverted": True}
    reopened = client.get("/projects/p1").json()
    assert [(e["edit_id"], e["reverted"]) for e in reopened["edits"]] == [("e1", True)]
    segments = client.post("/projects/p1/export").json()["segments"]
    assert [s["kind"] for s in segments] == ["original"]
    assert client.get("/projects").json()["projects"][0]["edits"] == 0


def test_reverting_an_unknown_edit_is_404(client, project):
    assert client.post("/projects/p1/edits/e9/revert").status_code == 404


def test_settings_say_what_voltage_may_do_and_round_trip(client, project):
    """20d: the autonomy, what one turn may spend and how hard Voltage thinks;
    the project's ceiling is read-only."""
    import app.api.main as main
    assert project["settings"] == {
        "autonomy": "ask", "turn_usd": main.settings.agent_turn_usd, "effort": main.settings.agent_effort,
        "ceiling_usd": main.ledger.ceiling_usd,
        # Volt: which steps still ask under Just do it, and the model (read-only).
        "ask_before": {"ship": False, "clone": False, "design": False}, "model": main.settings.agent_model,
    }

    resp = client.put("/projects/p1/settings", json={"turn_usd": 0.2, "effort": "xhigh"})

    assert resp.status_code == 200
    assert (resp.json()["settings"]["turn_usd"], resp.json()["settings"]["effort"]) == (0.2, "xhigh")
    saved = client.get("/projects/p1").json()["settings"]
    assert (saved["autonomy"], saved["turn_usd"], saved["effort"]) == ("ask", 0.2, "xhigh")
    # The cap is clamped to a cent and to the project's ceiling.
    assert client.put("/projects/p1/settings", json={"turn_usd": 0.001}).json()["settings"]["turn_usd"] == 0.01
    assert client.put("/projects/p1/settings", json={"turn_usd": 1e9}).json()["settings"]["turn_usd"] == round(main.ledger.ceiling_usd, 2)
    assert client.get("/projects/p1").json()["settings"]["effort"] == "xhigh"      # untouched by the cap changes
    assert client.put("/projects/p1/settings", json={"effort": "low"}).status_code == 422
    assert client.put("/projects/p1/settings", json={"turn_usd": "a lot"}).status_code == 422
    assert client.put("/projects/p1/settings", json={"autonomy": "yolo"}).status_code == 422


# ── plans: made by the agent's tools, shipped by approve ─────────────────────

GOAL = 'change "20% off" to "30% off"'


LINE = ("Get 20% off today only.", 0.0, 2.3)   # the canned clip's one line


def make_plan(client, items=(("Get 30% off today only.", "replace", "Offer"),), goal=GOAL, mode="ask",
              plan_id="plan1", project_id="p1", **fields):
    """Save a plan straight into the repo, as the agent's tools do. Each item
    is (new_text, mix, reason[, speaker]) on the canned clip's one line, or a
    dict of PlanItem fields."""
    import app.api.main as main
    from app.domain.models import Selection
    from app.domain.plan import Plan, PlanItem
    text, start, end = LINE
    built = []
    for n, i in enumerate(items):
        fields_ = dict(i) if isinstance(i, dict) else {
            "new_text": i[0], "mix": i[1], "reason": i[2], "speaker": i[3] if len(i) > 3 else None}
        built.append(PlanItem(item_id=f"i{n + 1}", selection=Selection(start, end), old_text=text, **fields_))
    built = tuple(built)
    plan = Plan(plan_id=plan_id, project_id=project_id, goal=goal, summary="Here's my plan.", items=built, mode=mode,
                status="proposed", created_at=main._now(), estimate=main._estimate(project_id, built), **fields)
    repo.save_plan(plan)
    n = len([i for i in built if i.kind == "planned"])
    repo.append_log(project_id, plan_id, f"Planned {n} {'change' if n == 1 else 'changes'}")
    return client.get(f"/projects/{project_id}/plans/{plan_id}").json()


def test_a_saved_plan_comes_back_with_the_project_and_by_its_id(client, project):
    plan = make_plan(client)

    assert plan["plan_id"] == "plan1" and plan["mode"] == "ask" and plan["status"] == "proposed"
    assert [(i["item_id"], i["old_text"], i["new_text"], i["status"], i["enabled"]) for i in plan["items"]] == [
        ("i1", "Get 20% off today only.", "Get 30% off today only.", "planned", True),
    ]
    assert plan["items"][0]["selection"] == {"start": 0.0, "end": 2.3}
    assert plan["estimate"]["items"] == 1 and plan["estimate"]["seconds"] > 0
    # The plan comes back with the project, and by its id.
    reopened = client.get("/projects/p1").json()
    assert reopened["plan"]["plan_id"] == "plan1"
    assert client.get("/projects/p1/plans/plan1").json()["goal"] == GOAL


def test_an_unknown_plan_is_404(client, project):
    assert client.get("/projects/p1/plans/plan9").status_code == 404
    assert client.post("/projects/p1/plans/plan9/approve", json={}).status_code == 404


# ── UX-5: a clip with no speech ──────────────────────────────────────────────

def test_a_silent_clip_shows_its_frames_where_the_transcript_would_be(client, project, monkeypatch):
    """UX-5: with no speech, the project shows its frames where the transcript
    would be."""
    import app.api.main as main
    from app.domain.models import Transcript
    speechless(monkeypatch, main, Transcript(words=()))
    frames = client.get("/projects/p1/frames").json()
    assert [f["index"] for f in frames] == [0, 1, 2]
    assert frames[0]["at"] == pytest.approx(0.3)
    frame = client.get("/projects/p1/frames/0")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    assert client.get("/projects/p1/frames/9").status_code == 404
    assert client.get("/projects/p1").json()["frames"] == frames


def test_a_turn_voices_the_line_then_approve_all_exports(client, project, monkeypatch):
    done = voiced(client, monkeypatch)
    plan_id = done["plan"]["plan_id"]

    [item] = done["plan"]["items"]
    assert done["plan"]["status"] == "done" and item["status"] == "ready"
    assert item["candidate"]["candidate_id"] == "c1" and item["candidate"]["continuity"]["passed"] is True
    assert any(e["text"].startswith("Voiced “Get 30% off") for e in done["plan"]["log"])

    resp = client.post(f"/projects/p1/plans/{plan_id}/approve", json={})
    body = resp.json()
    assert resp.status_code == 200
    assert body["approved"] == [{"item_id": "i1", "edit_id": "e1", "overridden": False, "speaker": None, "voice_profile_id": "mock"}]
    assert body["skipped"] == []
    assert [s["kind"] for s in body["export"]["segments"]] == ["edited"]
    assert body["plan"]["items"][0]["status"] == "approved" and body["plan"]["items"][0]["edit_id"] == "e1"
    assert body["plan"]["log"][-1]["text"] == "Rendered the edited video"
    assert [e["edit_id"] for e in client.get("/projects/p1").json()["edits"]] == ["e1"]


def test_a_failing_take_is_skipped_by_approve_all_unless_overridden(client, project, monkeypatch):
    client.post("/projects/p1/speakers/detect")
    client.put("/projects/p1/speakers/A", json={"voice_id": "unknown"})   # the mock engine fails this voice
    done = voiced(client, monkeypatch, voice_id="")                        # A's own voice: the one picked for them
    plan_id = done["plan"]["plan_id"]
    assert done["plan"]["items"][0]["candidate"]["continuity"]["passed"] is False

    body = client.post(f"/projects/p1/plans/{plan_id}/approve", json={}).json()
    assert body["approved"] == [] and body["skipped"] == [{"item_id": "i1", "reason": "continuity check failed"}]
    assert body["export"] is None

    body = client.post(f"/projects/p1/plans/{plan_id}/approve", json={"override": True}).json()
    assert body["approved"] == [{"item_id": "i1", "edit_id": "e1", "overridden": True, "speaker": "A", "voice_profile_id": "unknown"}]


def test_approving_a_plan_items_take_through_the_edit_route_marks_the_item(client, project, monkeypatch):
    done = voiced(client, monkeypatch)
    client.post("/projects/p1/edits", json={"candidate_id": done["plan"]["items"][0]["candidate"]["candidate_id"]})
    item = client.get(f"/projects/p1/plans/{done['plan']['plan_id']}").json()["items"][0]
    assert (item["status"], item["edit_id"]) == ("approved", "e1")


# ── the warm agentic pass: narration ─────────────────────────────────────────

def test_each_item_carries_what_is_happening_to_it_and_the_plans_spend(client, project, monkeypatch):
    import app.api.main as main
    from app.usage import claude_usd
    seen = []
    real_update = main.repo.update_item

    def spy(project_id, plan_id, item_id, **changes):
        if "progress" in changes and changes["progress"]:
            seen.append(changes["progress"])
        return real_update(project_id, plan_id, item_id, **changes)

    monkeypatch.setattr(main.repo, "update_item", spy)
    done = voiced(client, monkeypatch)
    assert "Synthesizing the new line" in seen and "Checking continuity" in seen
    assert done["plan"]["items"][0]["progress"] is None          # cleared once ready
    # The mock voice is free; the two Claude calls of the turn are the plan's whole spend.
    assert done["plan"]["spend_usd"] == pytest.approx(2 * claude_usd(main._agent_instance.model, 100, 20), abs=1e-4)
    assert done["plan"]["takes_voiced"] == 0                     # and records no takes (P-1)
    assert done["plan"]["items"][0]["candidate"]["words"] == []  # the mock has no word times (P-3)


def test_a_redone_take_says_why_it_is_being_redone(client, project, monkeypatch):
    import app.api.main as main
    from app.continuity.engine import Assessment
    from app.domain.models import ContinuityReport

    class Picky:
        """Fails the first take with a reason, passes the next."""

        def __init__(self):
            self.calls = 0

        def assess(self, source, transcript, plan, audio):
            self.calls += 1
            if self.calls == 1:
                return Assessment(report=ContinuityReport(None, 0.5, 0.9, None, False,
                                  ("Pitch is -6.3 semitones off the surrounding speech.",), ("prosody",)), audio=audio)
            return Assessment(report=ContinuityReport(None, 0.95, 0.9, None, True, (), ("prosody",)), audio=audio)

    monkeypatch.setattr(main, "continuity", Picky())
    monkeypatch.setattr(main.voice, "identity", "stock", raising=False)
    steps = []
    generate(report=lambda progress, step: steps.append(step))
    assert any(s.startswith("Take 1: pitch is -6.3 semitones off the surrounding speech. Trying again (take 2 of 3)") for s in steps)


def test_an_added_line_is_spoken_by_the_speaker_it_is_given_to(client, project):
    import app.api.main as main
    from app.domain.models import Selection
    client.post("/projects/p1/speakers/detect")
    client.put("/projects/p1/speakers/A", json={"name": "Presenter", "voice_id": "nPczCjzI2devNBz1zQrb"})
    record = main.repo.get("p1")

    choice = main._voice_for("p1", record, Selection(2.3, 2.3), "mock", speaker="A")   # no words there: A is named

    assert choice.voice_id == "nPczCjzI2devNBz1zQrb" and choice.notes == ()
    candidate = generate(text="Delivery is free.", start=2.3, end=2.3, voice_id=choice.voice_id, mix="concatenate")
    assert candidate["plan"]["voice_profile_id"] == "nPczCjzI2devNBz1zQrb"


# ── Phase 14: fit by writing and generation ──────────────────────────────────

def test_each_line_carries_its_syllables_and_its_budget(client, project):
    import app.api.main as main
    line = main._lines(main.repo.get("p1"))[0]
    assert line.syllables == 10 and line.budget >= 10


def test_takes_and_tolerance_come_from_the_environment(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv("AVE_TAKES_PER_LINE", "2")
    monkeypatch.setenv("AVE_FIT_TOLERANCE", "0.1")
    s = load_settings()
    assert (s.takes_per_line, s.fit_tolerance) == (2, 0.1)
    monkeypatch.setenv("AVE_TAKES_PER_LINE", "0")
    assert load_settings().takes_per_line == 1


def test_fit_notes_reach_the_candidate_and_survive_reopening(client, project, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main.voice, "last_notes", ["trimmed 90 ms of pauses"], raising=False)
    candidate = generate()
    assert candidate["fit_notes"] == ["trimmed 90 ms of pauses"]
    assert main.repo.get_candidate("p1", candidate["candidate_id"]).fit_notes == ("trimmed 90 ms of pauses",)


# ── UX-1: over the picture, remove a line, delivery ──────────────────────────

def test_an_added_line_plays_over_the_picture_when_there_is_room(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Transcript, Word
    # a 1.0 s pause after "off" before "today"
    speechless(monkeypatch, main, Transcript(words=(
        Word("Get", 0.0, 0.4), Word("20%", 0.4, 0.9), Word("off", 0.9, 1.3), Word("today", 2.3, 2.3),
    )))
    result = generate(text="Hurry!", mix="over", start=0.4, end=1.3)
    assert result["type"] == "candidate"
    assert result["plan"]["mix"] == "layer"
    assert result["plan"]["selection"] == {"start": 1.3, "end": pytest.approx(2.3, abs=0.02)}


def test_an_added_line_holds_the_picture_when_there_is_no_room(client, project):
    # the canned transcript has no pauses: "today" follows "off" at once
    result = generate(text="Hurry!", mix="over", start=0.4, end=1.3)
    assert result["type"] == "candidate"
    assert result["plan"]["mix"] == "concatenate"


def test_removing_a_line_is_a_proposal_that_ships_to_room_tone_and_can_be_undone(client, project):
    resp = client.post("/projects/p1/lines/remove", json={"start": 0.5, "end": 1.0})
    assert resp.status_code == 200
    body = resp.json()
    # 20e: a removal is proposed like a take — a ready plan item with the room's sound as its take.
    assert body["mix"] == "remove" and body["item_id"] == "i1"
    assert body["selection"] == {"start": 0.4, "end": 1.3}
    item = body["plan"]["items"][0]
    assert (item["status"], item["mix"], item["old_text"], item["new_text"]) == ("ready", "remove", "20% off", "")
    assert client.get("/projects/p1").json()["edits"] == []
    # With proposals, the preview render carries it; the final does not.
    preview = client.post("/projects/p1/export", json={"with_proposals": True}).json()
    assert preview["proposals"] == ["i1"] and [s["kind"] for s in preview["segments"]] == ["original", "edited", "original"]
    assert [s["kind"] for s in client.post("/projects/p1/export").json()["segments"]] == ["original"]
    # Add it: approving the item makes the edit.
    plan_id = body["plan"]["plan_id"]
    shipped = client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": ["i1"]}).json()
    assert [a["edit_id"] for a in shipped["approved"]] == ["e1"]
    edits = client.get("/projects/p1").json()["edits"]
    assert edits[0]["mix"] == "remove" and edits[0]["new_text"] == ""
    export = client.post("/projects/p1/export").json()
    edited = [s for s in export["segments"] if s["kind"] == "edited"]
    assert len(edited) == 1 and edited[0]["start"] == pytest.approx(0.4) and edited[0]["end"] == pytest.approx(1.3)
    assert client.post("/projects/p1/edits/e1/revert").status_code == 200
    assert [s["kind"] for s in client.post("/projects/p1/export").json()["segments"]] == ["original"]


def test_removing_nothing_is_refused(client, project):
    assert client.post("/projects/p1/lines/remove", json={"start": 5.0, "end": 5.0}).status_code == 422


def test_a_delivery_reaches_the_voice_and_the_candidate(client, project, monkeypatch):
    import app.api.main as main
    seen = []
    real = main.voice

    class Hears:
        identity = "mock"
        default_voice = "mock"

        def cost_of(self, plan):
            return 0

        def voices(self):
            return real.voices()

        def synthesize(self, source, plan, transcript=None):
            seen.append(plan.delivery)
            return real.synthesize(source, plan, transcript)

    monkeypatch.setattr(main, "voice", Hears())
    result = generate(text="Get 30% off.", mix="replace", delivery="warmer")
    assert seen == ["warmer"] and result["plan"]["delivery"] == "warmer"


# ── UX-1b: move a take or a kept line ────────────────────────────────────────

def test_a_take_can_be_moved_without_voicing_it_again(client, project):
    first = generate()
    moved = client.post(f"/projects/p1/candidates/{first['candidate_id']}/move", json={"start": 1.0}).json()
    assert moved["candidate_id"] != first["candidate_id"]
    assert moved["audio"]["sha256"] == first["audio"]["sha256"]           # the same audio
    assert moved["plan"]["selection"] == {"start": 1.0, "end": pytest.approx(1.0 + first["audio"]["duration"], abs=0.01)}
    assert moved["plan"]["fit"] == "start" and moved["fit_notes"][-1] == "moved to 0:01"
    assert client.get("/projects/p1/usage").json()["voice_characters"] == 0


def test_a_move_can_change_how_it_meets_the_sound(client, project):
    first = generate()
    layered = client.post(f"/projects/p1/candidates/{first['candidate_id']}/move", json={"start": 0.2, "mix": "layer"}).json()
    assert layered["plan"]["mix"] == "layer"
    held = client.post(f"/projects/p1/candidates/{first['candidate_id']}/move", json={"start": 2.0, "mix": "concatenate"}).json()
    assert held["plan"]["mix"] == "concatenate" and held["plan"]["selection"] == {"start": 2.0, "end": 2.0}


def test_a_move_is_clamped_to_the_video(client, project):
    first = generate()
    moved = client.post(f"/projects/p1/candidates/{first['candidate_id']}/move", json={"start": 9.0}).json()
    assert moved["plan"]["selection"]["start"] == pytest.approx(2.3)
    assert client.post("/projects/p1/candidates/c99/move", json={"start": 1.0}).status_code == 404


def test_a_kept_line_moves_in_one_step(client, project):
    first = generate()
    client.post("/projects/p1/edits", json={"candidate_id": first["candidate_id"]})

    resp = client.post("/projects/p1/edits/e1/move", json={"start": 1.3})

    assert resp.status_code == 200
    body = resp.json()
    assert body["reverted"] == "e1" and body["edit_id"] == "e2"
    edits = client.get("/projects/p1").json()["edits"]
    assert [(e["edit_id"], e["reverted"]) for e in edits] == [("e1", True), ("e2", False)]
    assert edits[1]["selection"]["start"] == pytest.approx(1.3)
    segments = client.post("/projects/p1/export").json()["segments"]
    edited = [s for s in segments if s["kind"] == "edited"]
    assert len(edited) == 1 and edited[0]["start"] == pytest.approx(1.3)


def test_a_removal_cannot_be_moved(client, project):
    rm = client.post("/projects/p1/lines/remove", json={"start": 0.5, "end": 1.0}).json()
    shipped = client.post(f"/projects/p1/plans/{rm['plan']['plan_id']}/approve", json={"items": [rm["item_id"]]}).json()
    assert client.post(f"/projects/p1/edits/{shipped['approved'][0]['edit_id']}/move", json={"start": 1.0}).status_code == 422


def test_a_line_can_be_mixed_as_background_before_and_after_it_is_added(client, project, monkeypatch):
    """20g: /candidates/{id}/level relevels a proposal (the item follows); /edits/{id}/level relevels a line in the video (revert + re-approve)."""
    from tests.agent.conftest import reply, text as said
    result = turn(client, monkeypatch, [reply(take("c", text="Woohoo!", line=None, start=0.0, end=2.0, level="background"), stop="tool_use"),
                                        reply(said("A cheer, under the words."))])
    item = result["plan"]["items"][0]
    assert item["status"] == "ready" and item["candidate"]["plan"]["level_db"] == -12.0
    plan_id = result["plan"]["plan_id"]
    # Louder as a proposal: a new take, the item follows it.
    up = client.post(f"/projects/p1/candidates/{item['candidate']['candidate_id']}/level", json={"level_db": 0}).json()
    assert up["plan"]["level_db"] is None and up["candidate_id"] != item["candidate"]["candidate_id"]
    assert client.get(f"/projects/p1/plans/{plan_id}").json()["items"][0]["candidate"]["candidate_id"] == up["candidate_id"]
    # Added, then softer in the video: the old edit reverted, the same take approved at -12.
    shipped = client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": ["i1"]}).json()
    edit_id = shipped["approved"][0]["edit_id"]
    down = client.post(f"/projects/p1/edits/{edit_id}/level", json={"level_db": -12}).json()
    assert down["reverted"] == edit_id and down["candidate"]["plan"]["level_db"] == -12.0
    edits = client.get("/projects/p1").json()["edits"]
    live = [x for x in edits if not x["reverted"]]
    assert [x["edit_id"] for x in live] == [down["edit_id"]] and live[0]["level_db"] == -12.0
    assert client.post("/projects/p1/edits/nope/level", json={"level_db": -12}).status_code == 404


def test_a_line_taken_out_says_so_on_its_row_until_it_is_added_again(client, project):
    """20h: Take it out leaves a proposal whose note says what Add it and Discard now do; adding it again clears the note."""
    import app.api.main as main
    rm = client.post("/projects/p1/lines/remove", json={"start": 0.5, "end": 1.0}).json()
    plan_id = rm["plan"]["plan_id"]
    shipped = client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": ["i1"]}).json()
    client.post(f"/projects/p1/edits/{shipped['approved'][0]['edit_id']}/revert")
    item = client.get(f"/projects/p1/plans/{plan_id}").json()["items"][0]
    assert item["status"] == "ready" and item["note"] == main.TAKEN_OUT
    client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": ["i1"]})
    assert client.get(f"/projects/p1/plans/{plan_id}").json()["items"][0]["note"] is None


def test_your_own_voice_is_uploaded_under_a_name_listed_and_deleted(client, tmp_path):
    """20i: POST /voices/mine clones a recording of at least 10 s under a name, with consent; GET /voices lists it as mine; DELETE forgets it."""
    short = tmp_path / "short.wav"
    ffmpeg.generate_tone(short, 3.0, 220)
    long = tmp_path / "me.wav"
    ffmpeg.generate_tone(long, 12.0, 220)
    with short.open("rb") as f:
        refused = client.post("/voices/mine", data={"name": "Me", "consent": "true"}, files={"file": ("short.wav", f, "audio/wav")})
    assert refused.status_code == 422 and "at least 10 s" in refused.json()["detail"]
    with long.open("rb") as f:
        no_consent = client.post("/voices/mine", data={"name": "Me", "consent": "false"}, files={"file": ("me.wav", f, "audio/wav")})
    assert no_consent.status_code == 403
    with long.open("rb") as f:
        made = client.post("/voices/mine", data={"name": "  Me  ", "consent": "true"}, files={"file": ("me.wav", f, "audio/wav")})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["name"] == "Me" and body["voice_id"].startswith("mock-clone-") and body["seconds"] == 12.0
    listed = client.get("/voices").json()
    assert [v["name"] for v in listed["mine"]] == ["Me"] and listed["voices"][0]["voice_id"] == "mock"
    with long.open("rb") as f:
        again = client.post("/voices/mine", data={"name": "me", "consent": "true"}, files={"file": ("me.wav", f, "audio/wav")})
    assert again.status_code == 409
    assert client.delete(f"/voices/mine/{body['voice_id']}").status_code == 204
    assert client.get("/voices").json()["mine"] == []
    assert client.delete(f"/voices/mine/{body['voice_id']}").status_code == 404


def test_a_proposal_can_be_discarded_but_a_shipped_line_cannot(client, project):
    rm = client.post("/projects/p1/lines/remove", json={"start": 0.5, "end": 1.0}).json()
    plan_id = rm["plan"]["plan_id"]
    assert client.post(f"/projects/p1/plans/{plan_id}/items/nope/dismiss").status_code == 404
    plan = client.post(f"/projects/p1/plans/{plan_id}/items/i1/dismiss").json()
    assert plan["items"][0]["status"] == "dismissed" and plan["items"][0]["enabled"] is False
    assert plan["log"][-1]["text"] == "You discarded the line at 0:00"
    rm2 = client.post("/projects/p1/lines/remove", json={"start": 0.5, "end": 1.0}).json()
    client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": [rm2["item_id"]]})
    assert client.post(f"/projects/p1/plans/{plan_id}/items/{rm2['item_id']}/dismiss").status_code == 409


# ── UX-2: the panel does one job ─────────────────────────────────────────────

class Looks:
    """A planner stand-in that looks at the frames and says what it saw."""

    identity = "claude"

    def __init__(self):
        self.calls = 0

    def look(self, frames, duration, meter=None):
        from app.orchestrator.planner import Sight
        self.calls += 1
        if meter is not None:
            meter("claude-opus-5", 200, 30)
        return Sight(opening=f"No one speaks. {duration:.1f} s of picture, {len(frames)} frames.",
                     setting="A beach at dusk.", place_guess="Goa, India", confidence="medium")


def test_reading_the_clip_names_roles_once_and_the_project_carries_it(client, project, monkeypatch):
    import app.api.main as main
    from app.orchestrator.planner import Reading, Role

    class Reader:
        identity = "claude"
        calls = 0

        def read(self, lines, meter=None):
            Reader.calls += 1
            meter("claude-opus-5", 300, 40)
            return Reading("One person, one line. The offer is said once, at 0:00.",
                           (Role("Speaker A", "Presenter", "Carries the whole clip."), Role("Nobody", "Ghost")))

    monkeypatch.setattr(main, "planner", Reader())
    client.post("/projects/p1/speakers/detect")
    assert client.get("/projects/p1").json()["reading"] is None

    reading = client.post("/projects/p1/reading", json={}).json()

    assert reading["opening"] == "One person, one line. The offer is said once, at 0:00."
    assert reading["roles"] == [{"label": "A", "role": "Presenter", "why": "Carries the whole clip."}]
    assert client.post("/projects/p1/reading", json={}).json()["opening"] == reading["opening"]
    assert Reader.calls == 1                                   # saved; read once
    assert client.get("/projects/p1").json()["reading"]["roles"][0]["role"] == "Presenter"
    client.post("/projects/p1/reading", json={"again": True})
    assert Reader.calls == 2
    usage = client.get("/projects/p1/usage").json()
    assert any(line["what"] == "reading" and line["calls"] == 2 for line in usage["lines"])
    # Confirming a role names the speaker through the usual route.
    named = client.put("/projects/p1/speakers/A", json={"name": "Presenter"}).json()
    assert named["speakers"][0]["name"] == "Presenter"


def test_reading_a_silent_clip_looks_at_the_picture_instead(client, project, monkeypatch):
    """UX-5, SV-1: nothing to read, so the reading is what Claude sees in the
    picture, kept with the project like any reading and metered as looking."""
    import app.api.main as main
    from app.domain.models import Transcript
    speechless(monkeypatch, main, Transcript(words=()))
    looks = Looks()
    monkeypatch.setattr(main, "planner", looks)
    resp = client.post("/projects/p1/reading", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["opening"] == "No one speaks. 2.3 s of picture, 3 frames."
    assert body["roles"] == []
    assert body["sight"]["opening"] == body["opening"] and body["sight"]["place_guess"] == "Goa, India"
    assert client.get("/projects/p1").json()["reading"] == body
    assert client.post("/projects/p1/reading", json={}).json() == body and looks.calls == 1   # looked once
    assert any(line["what"] == "looking" for line in client.get("/projects/p1/usage").json()["lines"])


def test_reading_without_claude_says_so(client, project, monkeypatch):
    """20d: there is no offline reading. Without a planner (no key, or dry
    run) the route says Voltage needs Claude, for a speech clip and a silent one."""
    import app.api.main as main
    from app.domain.models import Transcript
    assert main.planner is None                               # the suite blanks the key
    resp = client.post("/projects/p1/reading", json={})
    assert resp.status_code == 503 and "needs Claude" in resp.json()["detail"]
    speechless(monkeypatch, main, Transcript(words=()))
    resp = client.post("/projects/p1/reading", json={})
    assert resp.status_code == 503 and "needs Claude" in resp.json()["detail"]
    assert client.get("/projects/p1").json()["reading"] is None


# ── UX-3: review, ship, return ───────────────────────────────────────────────

def test_the_project_list_shows_each_projects_frame_state_and_last_change(client, project, monkeypatch):
    listed = client.get("/projects").json()["projects"][0]
    assert listed["state"] == "new" and listed["last_change"] == "Nothing changed yet"
    assert listed["media"]["sha256"] == project["media"]["sha256"] and listed["variant_of"] is None

    done = voiced(client, monkeypatch)
    listed = client.get("/projects").json()["projects"][0]
    assert listed["state"] == "draft" and listed["last_change"].startswith("Voiced “Get 30% off")

    client.post(f"/projects/p1/plans/{done['plan']['plan_id']}/approve", json={})
    listed = client.get("/projects").json()["projects"][0]
    assert listed["state"] == "shipped" and listed["edits"] == 1 and listed["last_change"] == "Rendered the edited video"


def test_shipping_some_lines_holds_the_rest_and_undo_returns_a_line_to_a_draft(client, project, monkeypatch):
    from tests.agent.conftest import reply, text as said
    done = turn(client, monkeypatch, [
        reply(take("c"), take("d", text="Thirty, friends.", line=None, start=1.3, end=2.3, mix="layer"), stop="tool_use"),
        reply(said("Two lines to hear.")),
    ])
    plan_id = done["plan"]["plan_id"]
    assert [i["status"] for i in done["plan"]["items"]] == ["ready", "ready"]

    shipped = client.post(f"/projects/p1/plans/{plan_id}/approve", json={"items": ["i1"]}).json()

    assert [a["item_id"] for a in shipped["approved"]] == ["i1"]
    assert [i["status"] for i in shipped["plan"]["items"]] == ["approved", "ready"]   # the second is held
    assert shipped["export"] is not None

    client.post("/projects/p1/edits/e1/revert")

    plan = client.get(f"/projects/p1/plans/{plan_id}").json()
    assert [(i["status"], i["edit_id"]) for i in plan["items"]] == [("ready", None), ("ready", None)]
    assert plan["items"][0]["candidate"]["candidate_id"] is not None       # the take is kept, as a draft
    assert plan["log"][-1]["text"] == "You undid the line at 0:00"
    assert client.get("/projects").json()["projects"][0]["state"] == "draft"


def test_a_variant_is_the_same_clip_with_the_plan_as_a_draft(client, project, monkeypatch):
    client.post("/projects/p1/speakers/detect")
    client.put("/projects/p1/speakers/A", json={"name": "Presenter", "voice_id": "nPczCjzI2devNBz1zQrb"})
    client.put("/projects/p1/settings", json={"effort": "xhigh"})
    done = voiced(client, monkeypatch)
    client.post(f"/projects/p1/plans/{done['plan']['plan_id']}/approve", json={})

    variant = client.post("/projects/p1/variants").json()

    assert variant["project_id"] == "p2" and variant["filename"] == "ad.mp4"
    assert variant["media"]["sha256"] == project["media"]["sha256"]
    assert variant["consent"] is not None and variant["settings"]["effort"] == "xhigh"
    assert variant["speakers"] == [{"label": "A", "name": "Presenter", "voice_id": "nPczCjzI2devNBz1zQrb"}]
    plan = variant["plan"]
    assert plan["plan_id"] == "plan1" and plan["goal"] == "make it 30% off" and plan["status"] == "proposed"
    assert [(i["new_text"], i["status"], i["candidate"], i["edit_id"]) for i in plan["items"]] == [
        ("Get 30% off today only.", "planned", None, None)]
    assert plan["estimate"]["items"] == 1
    assert plan["log"][-1]["text"] == "Made as a variant of ad.mp4, with its plan as a draft"
    assert client.get("/projects/p2/artifacts/" + variant["media"]["sha256"]).status_code == 200
    listed = client.get("/projects").json()["projects"]
    assert [(p["project_id"], p["state"], p["variant_of"]) for p in listed] == [("p2", "draft", "p1"), ("p1", "shipped", None)]
    # The original is untouched.
    assert done["plan"]["items"][0]["candidate"] is not None
    assert client.get(f"/projects/p1/plans/{done['plan']['plan_id']}").json()["items"][0]["status"] == "approved"
    # Deleting the variant leaves the original's media alone.
    client.delete("/projects/p2")
    assert client.get("/projects/p1/artifacts/" + project["media"]["sha256"]).status_code == 200


# ── Phase 9c: sign-in ────────────────────────────────────────────────────────

class FakeGoogle:
    """Signs in whoever the test says, after a real-looking redirect."""

    def __init__(self, who):
        from app.auth import Identity
        self.who = Identity(*who)
        self.exchanged = []

    def authorize_url(self, redirect_uri, state, challenge):
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}&redirect_uri={redirect_uri}&code_challenge={challenge}"

    def identity(self, code, redirect_uri, verifier):
        self.exchanged.append((code, redirect_uri, verifier))
        return self.who


def signed_in(monkeypatch, who=("42", "ash@example.com", "Ash", None), allow=(), public="http://localhost:5173"):
    """Turn sign-in on with a fake Google, and sign `who` in through the real
    routes. Returns the fake."""
    import app.api.main as main
    from dataclasses import replace
    monkeypatch.setattr(main, "settings", replace(
        main.settings, auth_mode="google", session_secret="s3cret", public_url=public, allowed_emails=allow,
    ))
    fake = FakeGoogle(who)
    monkeypatch.setattr(main, "oidc", fake)
    return fake


HEADERS = {"X-Requested-With": "voltage"}


def login(client):
    from urllib.parse import parse_qs, urlparse
    sent = client.get("/auth/login", follow_redirects=False)
    assert sent.status_code == 302
    state = parse_qs(urlparse(sent.headers["location"]).query)["state"][0]
    return client.get(f"/auth/callback?code=c0de&state={state}", follow_redirects=False)


def test_with_sign_in_on_nothing_is_reachable_until_you_sign_in(client, sample_video, monkeypatch):
    fake = signed_in(monkeypatch)
    assert client.get("/auth/me").json() == {"mode": "google", "user": None}
    assert client.get("/projects").status_code == 401
    assert client.get("/projects").json()["detail"] == "Sign in to continue."
    assert client.get("/health").status_code == 200          # the health check stays open

    sent = client.get("/auth/login", follow_redirects=False)
    assert sent.headers["location"].startswith("https://accounts.google.com/")
    assert "redirect_uri=http://localhost:5173/api/auth/callback" in sent.headers["location"]
    assert "ave_login" in sent.cookies

    back = login(client)
    assert back.status_code == 302 and back.headers["location"] == "http://localhost:5173/"
    assert fake.exchanged[0][0] == "c0de" and fake.exchanged[0][1] == "http://localhost:5173/api/auth/callback"
    assert client.get("/auth/me").json()["user"] == {"sub": "42", "email": "ash@example.com", "name": "Ash", "picture": None}
    assert client.get("/projects").json() == {"projects": []}

    # A write needs the header a cross-site form cannot send.
    resp = upload(client, sample_video)
    assert resp.status_code == 403 and "did not come from Voltage" in resp.json()["detail"]
    with open(sample_video, "rb") as handle:
        resp = client.post("/projects", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=HEADERS)
    assert resp.status_code == 200
    # ...and it belongs to the person who signed in.
    assert [p["project_id"] for p in client.get("/projects").json()["projects"]] == ["p1"]
    assert main_owner_of("p1") == "google:42"

    client.post("/auth/logout", headers=HEADERS)
    assert client.get("/auth/me").json()["user"] is None
    assert client.get("/projects").status_code == 401


def main_owner_of(project_id):
    import app.api.main as main
    return main.repo.get(project_id).owner


def test_a_stale_or_mismatched_login_is_refused(client, monkeypatch):
    signed_in(monkeypatch)
    assert client.get("/auth/callback?code=c&state=nope", follow_redirects=False).status_code == 400
    client.get("/auth/login", follow_redirects=False)
    assert client.get("/auth/callback?code=c&state=wrong", follow_redirects=False).status_code == 400
    assert client.get("/auth/callback?error=access_denied", follow_redirects=False).status_code == 400
    assert client.get("/auth/me").json()["user"] is None


def test_a_private_voltage_lets_only_listed_accounts_in(client, monkeypatch):
    signed_in(monkeypatch, who=("7", "stranger@else.com", "S", None), allow=("@example.com", "friend@x.y"))
    back = login(client)
    assert back.status_code == 403 and "private" in back.json()["detail"]
    assert client.get("/auth/me").json()["user"] is None
    signed_in(monkeypatch, who=("8", "me@example.com", "M", None), allow=("@example.com",))
    assert login(client).status_code == 302
    assert client.get("/auth/me").json()["user"]["email"] == "me@example.com"


def test_each_person_sees_only_their_own_projects(client, sample_video, monkeypatch):
    signed_in(monkeypatch, who=("1", "a@x.y", "A", None))
    login(client)
    with open(sample_video, "rb") as handle:
        client.post("/projects", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=HEADERS)
    signed_in(monkeypatch, who=("2", "b@x.y", "B", None))
    login(client)
    assert client.get("/projects").json()["projects"] == []
    assert client.get("/projects/p1").status_code == 404
    assert client.post("/projects/p1/export", headers=HEADERS).status_code == 404


def test_a_person_has_a_ceiling_across_their_projects(client, sample_video, monkeypatch):
    import app.api.main as main
    from dataclasses import replace
    signed_in(monkeypatch)
    monkeypatch.setattr(main, "settings", replace(main.settings, user_budget_usd=0.05))
    scripted = _agent_on(monkeypatch, main, [])

    class NeverRead:
        identity = "claude"

        def read(self, lines, meter=None):
            raise AssertionError("Claude was asked to read past the ceiling")

    monkeypatch.setattr(main, "planner", NeverRead())
    login(client)
    with open(sample_video, "rb") as handle:
        client.post("/projects", files={"file": ("ad.mp4", handle, "video/mp4")}, data={"consent": "true"}, headers=HEADERS)
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.06)
    usage = client.get("/projects/p1/usage").json()
    assert usage["user_spent_usd"] == 0.06 and usage["user_ceiling_usd"] == 0.05
    resp = client.post("/projects/p1/turns", json={"text": "make it 30% off"}, headers=HEADERS)
    assert resp.status_code == 202
    job = await_job(client, resp.json()["job_id"])
    assert job["status"] == "succeeded" and "across your projects" in job["result"]["reply"]
    assert scripted.calls == []                               # Claude was never called
    assert client.post("/projects/p1/reading", json={}, headers=HEADERS).status_code == 402


def test_with_sign_in_off_everything_is_as_before(client, project):
    assert client.get("/auth/me").json() == {"mode": "off", "user": None}
    assert client.get("/auth/login").status_code == 404
    assert client.get("/projects/p1/usage").json()["user_ceiling_usd"] is None


# ── UX-1c: shift a line of the original speech ──────────────────────────────

def test_a_line_can_be_shifted_to_another_time_without_voicing_it(client, project):
    moved = client.post("/projects/p1/lines/shift", json={"start": 0.5, "end": 1.0, "to": 1.5}).json()

    assert moved["mix"] == "layer" and moved["from"] == {"start": 0.4, "end": 1.3}      # snapped to the words "20% off"
    assert moved["selection"]["start"] == 1.5 and moved["selection"]["end"] == pytest.approx(2.3, abs=0.01)   # clamped to the clip
    assert moved["candidate"]["plan"]["new_text"] == "20% off" and moved["candidate"]["fit_notes"] == ["moved from 0:00"]
    assert moved["candidate"]["audio"]["duration"] == pytest.approx(0.9, abs=0.02)      # the original words, cut out
    edits = client.get("/projects/p1").json()["edits"]
    assert [(e["edit_id"], e["mix"], e["partner"], e["reverted"]) for e in edits] == [
        ("e1", "remove", "e2", False), ("e2", "layer", "e1", False)]
    # Rendered: room tone where the words were, the words over the picture at 1.5.
    manifest = client.post("/projects/p1/export").json()
    kinds = [(s["kind"], s["start"]) for s in manifest["segments"]]
    assert ("edited", 0.4) in kinds and ("edited", 1.5) in kinds
    assert client.get("/projects/p1").json()["messages"][-1]["text"] == "Moved the line at 0:00 to 0:01"


def test_undoing_a_shifted_line_undoes_both_halves(client, project):
    moved = client.post("/projects/p1/lines/shift", json={"start": 0.5, "end": 1.0, "to": 1.5}).json()
    client.post(f"/projects/p1/edits/{moved['removed_edit_id']}/revert")
    edits = client.get("/projects/p1").json()["edits"]
    assert [e["reverted"] for e in edits] == [True, True]
    assert [s["kind"] for s in client.post("/projects/p1/export").json()["segments"]] == ["original"]


def test_a_shifted_line_can_be_moved_again_and_stays_paired(client, project):
    moved = client.post("/projects/p1/lines/shift", json={"start": 0.5, "end": 1.0, "to": 1.5}).json()
    again = client.post(f"/projects/p1/edits/{moved['edit_id']}/move", json={"start": 1.2}).json()
    edits = {e["edit_id"]: e for e in client.get("/projects/p1").json()["edits"]}
    assert edits["e2"]["reverted"] is True
    assert edits["e3"]["partner"] == "e1" and edits["e1"]["partner"] == "e3" and edits["e3"]["selection"]["start"] == 1.2
    client.post("/projects/p1/edits/e1/revert")
    assert all(e["reverted"] for e in client.get("/projects/p1").json()["edits"].__iter__())


def test_shifting_silence_is_refused(client, project, monkeypatch):
    import app.api.main as main
    from app.domain.models import Transcript, Word
    speechless(monkeypatch, main, Transcript(words=(Word("Get", 0.0, 0.4),)))
    assert client.post("/projects/p1/lines/shift", json={"start": 1.5, "end": 2.0, "to": 0.1}).status_code == 422


def test_the_place_voltage_guessed_can_be_confirmed_or_corrected(client, project, monkeypatch):
    """UX-5: the sight's place is a decision, not a paragraph — confirmed or
    renamed, it is kept with the project and with the saved reading."""
    import app.api.main as main
    from app.domain.models import Transcript
    speechless(monkeypatch, main, Transcript(words=()))
    monkeypatch.setattr(main, "planner", Looks())
    client.post("/projects/p1/reading", json={})
    body = client.put("/projects/p1/sight", json={"place": "Morjim, Goa"}).json()
    assert body["place_confirmed"] == "Morjim, Goa"
    assert client.get("/projects/p1").json()["reading"]["sight"]["place_confirmed"] == "Morjim, Goa"
    assert client.put("/projects/p1/sight", json={"place": ""}).json()["place_confirmed"] == ""


def test_export_describes_the_output_as_pieces_and_nothing_is_held(client, project):
    """Phase 16: the manifest tiles the output. "today" follows "off" at once, so there is no
    pause to stretch after the added line; the tail of the line itself is the living window,
    and no frame is frozen."""
    candidate = generate(text="Hurry!", mix="concatenate", start=0.4, end=1.3)
    assert client.post("/projects/p1/edits", json={"candidate_id": candidate["candidate_id"]}).status_code == 200
    export = client.post("/projects/p1/export").json()
    pieces = export["pieces"]
    assert [p["kind"] for p in pieces] == ["copy", "living", "copy"]
    assert pieces[0]["out_start"] == 0.0 and pieces[-1]["out_end"] == pytest.approx(export["render"]["duration"], abs=0.1)
    living = pieces[1]
    assert living["end"] == pytest.approx(1.3, abs=0.05) and living["start"] == pytest.approx(0.9, abs=0.05)
    assert (living["out_end"] - living["out_start"]) - (living["end"] - living["start"]) == pytest.approx(candidate["audio"]["duration"], abs=0.05)
    assert living["factor"] > 1.0
    [insert] = export["inserts"]
    assert insert["held"] == 0.0
    # The cuts were looked for once and kept with the project.
    assert client.get("/projects/p1").json()  # still fine
    export_again = client.post("/projects/p1/export").json()
    assert export_again["pieces"] == pieces


def test_a_plan_without_edits_exports_copies_only(client, project):
    export = client.post("/projects/p1/export").json()
    assert [p["kind"] for p in export["pieces"]] == ["copy"]
    assert export["inserts"] == []


# ── 15e: a voice the goal asks for ────────────────────────────────────────────

def test_an_asked_voice_speaks_the_line_ahead_of_the_speakers_own(client, project, monkeypatch):
    client.post("/projects/p1/speakers/detect")
    client.put("/projects/p1/speakers/A", json={"voice_id": "picked-for-A-on-purpose"})
    result = voiced(client, monkeypatch, voice_id="mock")    # the voice Voltage names, not A's
    assert result["plan"]["items"][0]["candidate"]["plan"]["voice_profile_id"] == "mock"


# ── Phase 20a: a turn of Voltage with tools ───────────────────────────────────

def test_without_the_flag_a_turn_says_voltage_needs_claude(client, project, monkeypatch):
    import app.api.main as main
    from dataclasses import replace
    # The flag is on by default now (20c); a key alone must not open the route with it off.
    monkeypatch.setattr(main, "settings", replace(main.settings, agent=False, anthropic_api_key="k"))
    resp = client.post("/projects/p1/turns", json={"text": "make it 30% off"})
    assert resp.status_code == 503 and "AVE_AGENT" in resp.json()["detail"]


def test_a_turn_voices_a_line_through_the_tools_and_the_thread_shows_each_step(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    _agent_on(monkeypatch, main, [
        reply(use("read_transcript", "a"), use("list_voices", "b"), stop="tool_use"),
        reply(use("synthesize_take", "c", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None,
                  direction="brisk and confident", mix=None, item_id=None), stop="tool_use"),
        reply(text("Line 1 now says 30% off, brisk. Hear it; say ship when you're happy.")),
    ])
    assert client.get("/projects/p1").json()["agent"] is True
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    resp = client.post("/projects/p1/turns", json={"text": "make it 30% off"})
    assert resp.status_code == 202, resp.text
    job = await_job(client, resp.json()["job_id"])
    result = job["result"]
    assert result["type"] == "turn" and result["reply"].startswith("Line 1 now says 30% off")
    assert result["question"] is None and result["calls"] == 3
    plan = result["plan"]
    assert plan["status"] == "done" and plan["summary"] == result["reply"]
    [item] = plan["items"]
    assert (item["status"], item["new_text"], item["old_text"], item["delivery"]) == ("ready", "Get 30% off today only.", "Get 20% off today only.", "firmer")
    assert item["candidate"]["plan"]["voice_profile_id"] == "mock"
    messages = client.get("/projects/p1/messages").json()
    kinds = [(m["role"], m["kind"], m["text"]) for m in messages]
    assert kinds[0] == ("user", "say", "make it 30% off")
    assert ("assistant", "step", "Read all 1 line") in kinds and ("assistant", "step", "Looked through 1 voices") in kinds
    voiced_ = next(m for m in messages if m["kind"] == "step" and m["text"].startswith("Voiced “Get 30% off"))
    assert voiced_["text"] == "Voiced “Get 30% off today only.” with Test tone — brisk and confident"
    assert kinds[-2] == ("assistant", "say", result["reply"]) and kinds[-1][:2] == ("assistant", "step")   # then "Thinking", its own cost
    later = client.get("/projects/p1/messages", params={"after": messages[-3]["seq"]}).json()
    assert [m["text"] for m in later] == [result["reply"], "Thinking"]
    # The model's thread is kept as it saw it, append-only.
    turns = main.repo.turns("p1")
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert turns[0]["content"][0]["text"].startswith("The clip: ad.mp4, 2.3 s, no speech") or "one speaker" in turns[0]["content"][0]["text"]
    assert any(e["text"].startswith("Voiced “Get 30% off") for e in plan["log"])


def test_under_check_with_me_the_turn_ends_with_a_question_and_go_resumes_it(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    client.put("/projects/p1/settings", json={"autonomy": "ask"})
    take_ = use("synthesize_take", "c", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None,
                direction=None, mix=None, item_id=None)
    scripted = _agent_on(monkeypatch, main, [
        reply(take_, stop="tool_use"),
        reply(text("Voicing it now."), use("synthesize_take", "d", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None,
                                             direction=None, mix=None, item_id=None), stop="tool_use"),
        reply(text("Done. Hear it below.")),
    ])
    resp = client.post("/projects/p1/turns", json={"text": "make it 30% off"})
    job = await_job(client, resp.json()["job_id"])
    result = job["result"]
    assert result["question"]["text"] == "Voice “Get 30% off today only.” in Test tone's voice, about $0.00?"
    assert result["plan"]["status"] == "clarifying" and result["plan"]["question"]["options"] == ["Go ahead", "Not yet"]
    assert result["plan"]["items"] == []
    # A second turn while the first is still open is refused; "go" resumes with the same thread.
    resp = client.post("/projects/p1/turns", json={"text": "go"})
    job = await_job(client, resp.json()["job_id"])
    result = job["result"]
    assert result["reply"] == "Done. Hear it below." and result["plan"]["status"] == "done"
    assert [i["status"] for i in result["plan"]["items"]] == ["ready"]
    second = scripted.calls[1]["messages"]
    assert second[-1]["content"][-1]["text"] == "The user says: go (They are answering yes to what you asked.)"
    assert len(second) == 4   # the first turn's three messages, then this one


def test_under_check_with_me_the_yes_to_a_paid_step_needs_consent(client, project_without_consent, monkeypatch):
    """20d: looking and asking cost the speaker nothing, so a turn under Check
    with me runs without consent; the yes that would voice them does not."""
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    client.put("/projects/p1/settings", json={"autonomy": "ask"})
    scripted = _agent_on(monkeypatch, main, [
        reply(take("c"), stop="tool_use"),
        reply(said("Voicing it now."), take("d"), stop="tool_use"),
        reply(said("Done. Hear it below.")),
    ])
    result = send(client, "make it 30% off")
    assert result["question"]["gate"] is True and result["plan"]["status"] == "clarifying"

    resp = client.post("/projects/p1/turns", json={"text": "go"})

    assert resp.status_code == 403 and "right to edit and clone" in resp.json()["detail"]
    assert client.post("/projects/p1/turns", json={"text": "do it", "approve": True}).status_code == 403
    assert len(scripted.calls) == 1                                  # nothing ran
    assert client.get("/projects/p1").json()["plan"]["status"] == "clarifying"   # still waiting for the yes

    client.post("/projects/p1/consent")
    result = send(client, "go")
    assert result["reply"] == "Done. Hear it below." and [i["status"] for i in result["plan"]["items"]] == ["ready"]


def test_a_turn_refused_at_the_ceiling_or_while_another_runs(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    _agent_on(monkeypatch, main, [reply(text("Nothing to do."))])
    main.ledger.record("p1", "elevenlabs", "take", 1, "characters", 5.0)
    resp = client.post("/projects/p1/turns", json={"text": "anything"})
    job = await_job(client, resp.json()["job_id"])
    assert "ceiling" in job["result"]["reply"].lower() or "spend" in job["result"]["reply"].lower()
    assert job["result"]["plan"]["status"] == "proposed"


def test_a_previews_card_reaches_the_thread_with_its_facts(client, project):
    """20b: a card message (voices to hear) carries its data to the panel; plain messages carry none."""
    import app.api.main as main
    main.repo.add_message("p1", "assistant", "3 voices designed from “an older woman”", kind="previews",
                          data={"description": "an older woman", "previews": [{"n": 1, "generated_voice_id": "g1", "sha256": "a" * 64, "duration": 25.2}]})
    main.repo.add_message("p1", "assistant", "Say which one.")
    card, said = client.get("/projects/p1/messages").json()[-2:]
    assert card["kind"] == "previews" and card["data"]["previews"][0]["generated_voice_id"] == "g1"
    assert said == {"role": "assistant", "text": "Say which one.", "kind": "say", "seq": card["seq"] + 1}


def test_a_turn_after_a_finished_turn_keeps_working_on_the_lines_not_yet_shipped(client, project, monkeypatch):
    """20b: a plan marked done at the end of a turn still holds the voiced
    lines; the next turn works on them rather than starting empty."""
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    client.put("/projects/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [
        reply(use("synthesize_take", "c", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None,
                  direction=None, mix=None, item_id=None, model=None, settings=None), stop="tool_use"),
        reply(text("Hear it.")),
        reply(use("project_state", "d"), stop="tool_use"),
        reply(text("Still there.")),
    ])
    first = await_job(client, client.post("/projects/p1/turns", json={"text": "make it 30% off"}).json()["job_id"])["result"]
    assert first["plan"]["status"] == "done" and [i["status"] for i in first["plan"]["items"]] == ["ready"]
    second = await_job(client, client.post("/projects/p1/turns", json={"text": "and then?"}).json()["job_id"])["result"]
    assert second["plan"]["plan_id"] == first["plan"]["plan_id"]
    assert [i["status"] for i in second["plan"]["items"]] == ["ready"]
    # The model saw the line in its state.
    state = next(b for m in main.repo.turns("p1") for b in (m["content"] if isinstance(m["content"], list) else [])
                 if b.get("type") == "tool_result" and b.get("tool_use_id") == "d")
    assert "i1 at" in state["content"] and "ready, take" in state["content"]


def test_moving_a_take_by_hand_carries_its_plan_item_along(client, project, monkeypatch):
    """20d: the row's Move on a take Voltage made updates the item that holds
    it, so Keep ships the moved take and the plan shows where it sits now."""
    voiced(client, monkeypatch)
    [item] = client.get("/projects/p1/plans/plan1").json()["items"] if client.get("/projects/p1/plans/plan1").status_code == 200 else client.get("/projects/p1").json()["plan"]["items"]
    assert item["status"] == "ready" and item["candidate"]
    moved = client.post(f"/projects/p1/candidates/{item['candidate']['candidate_id']}/move", json={"start": 1.0}).json()
    [after] = client.get("/projects/p1").json()["plan"]["items"]
    assert after["candidate"]["candidate_id"] == moved["candidate_id"]
    assert after["selection"]["start"] == 1.0 and after["candidate"]["fit_notes"][-1] == "moved to 0:01"


def test_a_turn_ends_with_what_voltages_own_thinking_cost_as_a_step(client, project, monkeypatch):
    """20d: the tools say what they spent; the turn's Claude cost is a step of
    its own after Voltage's words, so the thread's total is the turn's total."""
    voiced(client, monkeypatch)
    messages = client.get("/projects/p1/messages").json()
    last = messages[-1]
    assert last["kind"] == "step" and last["text"] == "Thinking" and last["cost"] > 0
    assert messages[-2]["text"] == "Hear it."
    usage = client.get("/projects/p1/usage").json()
    claude = sum(u["usd"] for u in usage["lines"] if u["vendor"] == "anthropic")
    assert last["cost"] == pytest.approx(claude, abs=1e-4)


# ── Volt: the user's defaults, and still asking under Just do it ──────────────

def test_my_defaults_round_trip_and_a_new_project_starts_from_them(client, sample_video):
    import app.api.main as main
    assert client.get("/me/settings").json() == {
        "autonomy": "ask", "turn_usd": main.settings.agent_turn_usd, "effort": main.settings.agent_effort,
        "ask_before": {"ship": False, "clone": False, "design": False}}
    resp = client.put("/me/settings", json={"autonomy": "draft", "ask_before": {"ship": True}})
    assert resp.status_code == 200
    assert resp.json()["autonomy"] == "draft" and resp.json()["ask_before"] == {"ship": True, "clone": False, "design": False}
    assert client.put("/me/settings", json={"turn_usd": 1e9}).json()["turn_usd"] == round(main.ledger.ceiling_usd, 2)
    assert client.put("/me/settings", json={"effort": "low"}).status_code == 422
    # A project made now starts from them; a later change to the defaults leaves it alone.
    made = upload(client, sample_video).json()
    assert made["settings"]["autonomy"] == "draft" and made["settings"]["ask_before"]["ship"] is True
    assert made["settings"]["model"] == main.settings.agent_model
    client.put("/me/settings", json={"autonomy": "ask"})
    assert client.get("/projects/p1/settings").json()["settings"]["autonomy"] == "draft"
    # A variant keeps the original's settings; the defaults fill only what it never set.
    client.put("/projects/p1/settings", json={"effort": "xhigh"})
    variant = client.post("/projects/p1/variants").json()
    assert (variant["settings"]["effort"], variant["settings"]["autonomy"], variant["settings"]["ask_before"]["ship"]) == ("xhigh", "draft", True)


def test_project_settings_carry_ask_before_and_the_model(client, project):
    import app.api.main as main
    assert project["settings"]["ask_before"] == {"ship": False, "clone": False, "design": False}
    assert project["settings"]["model"] == main.settings.agent_model
    resp = client.put("/projects/p1/settings", json={"ask_before": {"design": True, "other": True}})
    assert resp.json()["settings"]["ask_before"] == {"ship": False, "clone": False, "design": True}
    assert client.get("/projects/p1/settings").json()["settings"]["ask_before"]["design"] is True
    assert client.put("/projects/p1/settings", json={"ask_before": {"ship": "maybe"}}).status_code == 422
    assert client.get("/projects/p9/settings").status_code == 404


def test_under_just_do_it_a_step_the_user_chose_to_be_asked_about_waits_for_their_yes(client, project, monkeypatch):
    """Volt: Settings can keep a yes on shipping even under Just do it; the
    gate question says what the step costs and what the turn has left."""
    import app.api.main as main
    from tests.agent.conftest import reply, text as said, use
    client.put("/projects/p1/settings", json={"autonomy": "draft", "ask_before": {"ship": True}})
    _agent_on(monkeypatch, main, [
        reply(take("c"), stop="tool_use"),
        reply(use("ship", "d", item_ids=[], anyway=False), stop="tool_use"),
        reply(use("ship", "e", item_ids=[], anyway=False), stop="tool_use"),
        reply(said("Shipped.")),
    ])
    result = send(client, "make it 30% off and ship it")
    question = result["question"]
    assert question["text"] == "Ship 1 change and render the video?" and question["gate"] is True
    assert question["cost_usd"] is None
    spent = client.get("/projects/p1/usage").json()["spent_usd"]
    assert question["left_usd"] == round(main.settings.agent_turn_usd - spent, 2)
    assert result["plan"]["status"] == "clarifying" and result["plan"]["question"]["left_usd"] == question["left_usd"]
    assert client.get("/projects/p1").json()["edits"] == []
    result = send(client, "go")
    assert result["reply"] == "Shipped." and [e["edit_id"] for e in client.get("/projects/p1").json()["edits"]] == ["e1"]


def test_a_paid_gate_question_carries_the_steps_price(client, project, monkeypatch):
    import app.api.main as main
    _agent_on(monkeypatch, main, [reply_take_under_ask()])
    client.put("/projects/p1/settings", json={"autonomy": "ask"})
    result = send(client, "make it 30% off")
    assert result["question"]["cost_usd"] == 0.0 and 0 < result["question"]["left_usd"] <= main.settings.agent_turn_usd


def reply_take_under_ask():
    from tests.agent.conftest import reply
    return reply(take("c"), stop="tool_use")


def test_steps_carry_their_tool_and_time_in_the_turn(client, project, monkeypatch):
    """Volt: the trace shows which tool each step was and when it landed."""
    voiced(client, monkeypatch)
    steps = [m for m in client.get("/projects/p1/messages").json() if m["kind"] == "step"]
    assert [s["data"]["tool"] for s in steps] == ["synthesize_take", "thinking"]
    assert all(isinstance(s["data"]["t"], float) and s["data"]["t"] >= 0 for s in steps)
    assert steps[0]["data"]["t"] <= steps[1]["data"]["t"]


def test_an_edit_says_who_it_is_for_and_whose_voice_says_it(client, project, monkeypatch):
    """Volt: the rows show "+ New line · Riya" and the stand-in voice from the edit itself."""
    client.post("/projects/p1/speakers/detect")
    done = voiced(client, monkeypatch, voice_id="")        # line 1 is A's; the mock cannot clone, so the default speaks
    plan_id = done["plan"]["plan_id"]
    shipped = client.post(f"/projects/p1/plans/{plan_id}/approve", json={}).json()
    assert [(a["speaker"], a["voice_profile_id"]) for a in shipped["approved"]] == [("A", "mock")]
    [edit] = client.get("/projects/p1").json()["edits"]
    assert (edit["speaker"], edit["voice_profile_id"]) == ("A", "mock")
    # A removal has no voice; approving a take by hand says the same.
    removed = client.post("/projects/p1/lines/remove", json={"start": 1.3, "end": 1.8}).json()
    by_hand = client.post("/projects/p1/edits", json={"candidate_id": removed["candidate_id"]}).json()
    assert (by_hand["speaker"], by_hand["voice_profile_id"]) == (None, None)
    assert [(e["speaker"], e["voice_profile_id"]) for e in client.get("/projects/p1").json()["edits"]] == [("A", "mock"), (None, None)]


# ── Volt: usage across projects ──────────────────────────────────────────────

def test_usage_across_projects_counts_turns_takes_and_money_in_the_period(client, project, monkeypatch):
    import app.api.main as main
    voiced(client, monkeypatch)
    main.ledger.record("p1", "elevenlabs", "speech", 40, "characters", 0.012)
    # A row from long ago is outside the week and the month, inside all time.
    with main.database.tx() as c:
        c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  ("p1", "openai", "transcription", 1.0, "minutes", 0.006, "2000-01-01T00:00:00+00:00"))
    month = client.get("/usage").json()
    claude = sum(u["usd"] for u in client.get("/projects/p1/usage").json()["lines"] if u["vendor"] == "anthropic")
    assert (month["period"], month["turns"], month["takes"], month["voices_made"]) == ("month", 1, 1, 0)
    assert month["spent_usd"] == pytest.approx(claude + 0.012, abs=1e-4) and month["avg_turn_usd"] == pytest.approx(claude, abs=1e-4)
    assert (month["ceiling_usd"], month["project_cap_usd"]) == (main.settings.user_budget_usd, main.ledger.ceiling_usd)
    assert [(v["vendor"], v["label"]) for v in month["by_vendor"]] == [
        ("anthropic", "Voltage thinking"), ("elevenlabs", "Voices and takes"), ("openai", "Transcription")]
    assert next(v["usd"] for v in month["by_vendor"] if v["vendor"] == "openai") == 0.0
    [p1] = month["by_project"]
    assert (p1["project_id"], p1["filename"], p1["turns"], p1["voice_characters"], p1["cap_usd"]) == ("p1", "ad.mp4", 1, 40, main.ledger.ceiling_usd)
    assert p1["spent_usd"] == pytest.approx(month["spent_usd"], abs=1e-4)
    everything = client.get("/usage", params={"period": "all"}).json()
    assert everything["spent_usd"] == pytest.approx(month["spent_usd"] + 0.006, abs=1e-4)
    assert client.get("/usage", params={"period": "week"}).json()["turns"] == 1
    assert client.get("/usage", params={"period": "year"}).status_code == 422
    # Someone else sees nothing of it.
    main.app.dependency_overrides[main.current_owner] = lambda: "someone-else"
    try:
        assert client.get("/usage").json()["by_project"] == [] and client.get("/usage").json()["spent_usd"] == 0.0
    finally:
        main.app.dependency_overrides.clear()


# ── Volt: voices ─────────────────────────────────────────────────────────────

def my_voice(client, tmp_path, name="Me"):
    me = tmp_path / f"{name}.wav"
    ffmpeg.generate_tone(me, 12.0, 220)
    with me.open("rb") as f:
        made = client.post("/voices/mine", data={"name": name, "consent": "true"}, files={"file": (me.name, f, "audio/wav")})
    assert made.status_code == 201, made.text
    return made.json()


def test_voices_carry_a_preview_a_kind_a_sample_and_the_slots(client, project, tmp_path, monkeypatch):
    import app.api.main as main
    body = client.get("/voices").json()
    assert body["voices"][0]["preview_url"] is None and body["slots"] is None and body["mine"] == []
    made = my_voice(client, tmp_path)
    assert (made["kind"], made["description"], made["used_in"]) == ("recorded", None, 0) and len(made["sample_sha"]) == 64
    [mine] = client.get("/voices").json()["mine"]
    assert (mine["kind"], mine["sample_sha"], mine["used_in"]) == ("recorded", made["sample_sha"], 0)
    sample = client.get(f"/voices/sample/{made['sample_sha']}")
    assert sample.status_code == 200 and sample.headers["content-type"] == "audio/wav"
    assert client.get(f"/voices/sample/{made['sample_sha']}", headers={"Range": "bytes=0-99"}).status_code == 206
    assert client.get("/voices/sample/" + "0" * 64).status_code == 404
    main.app.dependency_overrides[main.current_owner] = lambda: "someone-else"
    try:
        assert client.get(f"/voices/sample/{made['sample_sha']}").status_code == 404
    finally:
        main.app.dependency_overrides.clear()
    # A take in the voice counts the project as using it.
    voiced(client, monkeypatch, voice_id=made["voice_id"])
    assert client.get("/voices").json()["mine"][0]["used_in"] == 1
    # The vendor's slots, when it can say.
    monkeypatch.setattr(main.voice, "slots", lambda: (3, 30), raising=False)
    assert client.get("/voices").json()["slots"] == [3, 30]


def test_a_speaker_with_enough_speech_can_become_one_of_my_voices(client, tmp_path):
    import app.api.main as main
    from app.domain.models import Transcript, Word
    from tests.conftest import _mux
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 12.0)
    audio, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 12.0)
    assert upload(client, _mux(video, audio, tmp_path / "talk.mp4"), name="talk.mp4").status_code == 200
    words = tuple(Word(f"w{i}", float(i), i + 0.9, speaker="A") for i in range(11)) + (Word("hm", 11.0, 11.9, speaker="B"),)
    main.repo.update_transcript("p1", Transcript(words=words))
    client.put("/projects/p1/speakers/A", json={"name": "Presenter"})
    assert client.get("/voices/speakers").json() == {"speakers": [
        {"project_id": "p1", "filename": "talk.mp4", "label": "A", "name": "Presenter", "seconds": 10.9}]}
    ask = {"project_id": "p1", "label": "A", "name": "Presenter", "consent": True}
    assert client.post("/voices/mine/from-speaker", json={**ask, "consent": False}).status_code == 403
    assert client.post("/voices/mine/from-speaker", json={**ask, "label": "B"}).status_code == 422
    assert client.post("/voices/mine/from-speaker", json={**ask, "label": "Z"}).status_code == 404
    assert client.post("/voices/mine/from-speaker", json={**ask, "project_id": "p9"}).status_code == 404
    made = client.post("/voices/mine/from-speaker", json=ask)
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["kind"], body["name"], body["seconds"]) == ("cloned", "Presenter", 10.9) and body["voice_id"].startswith("mock-clone-")
    assert client.get(f"/voices/sample/{body['sample_sha']}").status_code == 200
    assert client.post("/voices/mine/from-speaker", json=ask).status_code == 409
    # The sample is the owner's now: the project can go.
    client.delete("/projects/p1")
    assert client.get(f"/voices/sample/{body['sample_sha']}").status_code == 200


class Remembering(MockVoiceAdapter):
    """The mock voice, remembering what it is asked to delete."""

    def __init__(self, store):
        super().__init__(store)
        self.deleted: list[str] = []

    def delete_voice(self, voice_id):
        self.deleted.append(voice_id)

    delete_clone = delete_voice


def test_a_voice_made_for_a_clip_can_be_kept_as_mine_and_then_outlives_the_project(client, project, monkeypatch):
    import app.api.main as main
    from app.orchestrator.clones import CloneService
    voice = Remembering(main.artifacts)
    monkeypatch.setattr(main, "voice", voice)
    monkeypatch.setattr(main, "clones", CloneService(main.repo, main.artifacts, voice))
    client.post("/projects/p1/speakers/detect")
    client.put("/projects/p1/speakers/A", json={"name": "Presenter"})
    main.repo.set_settings("p1", made_voices=[
        {"voice_id": "DESIGNED1", "name": "Dusk", "kind": "designed", "description": "an older woman", "at": main._now()},
        {"voice_id": "LIB1", "name": "Riya", "kind": "library", "at": main._now()}])
    main.repo.set_clone("p1", "A", "CLONEA")
    made = client.get("/voices/made").json()["voices"]
    assert [(v["voice_id"], v["name"], v["kind"], v["kept"]) for v in made] == [
        ("DESIGNED1", "Dusk", "designed", False), ("LIB1", "Riya", "library", False), ("CLONEA", "Presenter", "cloned", False)]
    assert made[0]["description"] == "an older woman" and made[0]["seconds"] is None and made[2]["seconds"] == 2.3
    assert all(v["project_id"] == "p1" and v["filename"] == "ad.mp4" for v in made)

    kept = client.post("/voices/mine/keep", json={"voice_id": "DESIGNED1"})
    assert kept.status_code == 201, kept.text
    assert (kept.json()["name"], kept.json()["kind"], kept.json()["description"]) == ("Dusk", "designed", "an older woman")
    assert client.post("/voices/mine/keep", json={"voice_id": "DESIGNED1"}).status_code == 409
    assert client.post("/voices/mine/keep", json={"voice_id": "NOPE"}).status_code == 404
    assert client.post("/voices/mine/keep", json={"voice_id": "CLONEA", "name": "dusk"}).status_code == 409   # a name in use
    kept = client.post("/voices/mine/keep", json={"voice_id": "CLONEA", "name": "My presenter"}).json()
    assert (kept["kind"], kept["seconds"]) == ("cloned", 2.3)
    assert [m["voice_id"] for m in main.repo.settings("p1")["made_voices"]] == ["LIB1"]
    assert [(v["voice_id"], v["kept"]) for v in client.get("/voices/made").json()["voices"]] == [("LIB1", False), ("CLONEA", True)]
    assert [v["name"] for v in client.get("/voices").json()["mine"]] == ["Dusk", "My presenter"]
    # Deleting the project takes the voice it still owns with it; the kept ones stay at the vendor.
    assert client.delete("/projects/p1").status_code == 204
    assert voice.deleted == ["LIB1"]
    assert [v["name"] for v in client.get("/voices").json()["mine"]] == ["Dusk", "My presenter"]


def test_a_voice_is_designed_outside_any_project_and_a_preview_kept_as_mine(client, monkeypatch):
    import app.api.main as main
    resp = client.post("/voices/design", json={"description": "  an older woman,  unhurried "})
    assert resp.status_code == 200, resp.text
    previews = resp.json()["previews"]
    assert len(previews) == 3 and all(len(p["sha256"]) == 64 and p["duration"] == 1.0 and p["text"] for p in previews)
    assert previews[0]["generated_voice_id"].startswith("mock-preview-")
    assert client.get(f"/voices/sample/{previews[1]['sha256']}").status_code == 200
    keep = {"generated_voice_id": previews[1]["generated_voice_id"], "name": "Dusk", "sha256": previews[1]["sha256"],
            "description": "", "consent": True}
    assert client.post("/voices/mine/from-preview", json={**keep, "consent": False}).status_code == 403
    kept = client.post("/voices/mine/from-preview", json=keep)
    assert kept.status_code == 201, kept.text
    body = kept.json()
    assert (body["kind"], body["name"], body["sample_sha"], body["description"]) == ("designed", "Dusk", previews[1]["sha256"], "an older woman, unhurried")
    assert body["voice_id"].startswith("mock-designed-")
    assert [v["name"] for v in client.get("/voices").json()["mine"]] == ["Dusk"]
    assert client.post("/voices/design", json={"description": "   "}).status_code == 422
    # The ceiling applies to the owner's own spend too.
    main.ledger.record("user-local", "elevenlabs", "speech", 1, "characters", main.ledger.ceiling_usd)
    assert client.post("/voices/design", json={"description": "a man"}).status_code == 402
    # Without a vendor that designs, the page is told so.
    monkeypatch.delattr(MockVoiceAdapter, "design_voice")
    assert client.post("/voices/design", json={"description": "a man"}).status_code == 503


def test_deleting_the_account_removes_every_project_voice_and_default(client, project, tmp_path, monkeypatch):
    import app.api.main as main
    mine = my_voice(client, tmp_path)
    client.put("/me/settings", json={"autonomy": "draft"})
    deleted = []
    monkeypatch.setattr(main.voice, "delete_voice", deleted.append)
    assert client.delete("/account").status_code == 204
    assert client.get("/projects").json()["projects"] == [] and client.get("/projects/p1").status_code == 404
    assert client.get("/voices").json()["mine"] == [] and deleted == [mine["voice_id"]]
    assert client.get(f"/voices/sample/{mine['sample_sha']}").status_code == 404
    assert client.get("/me/settings").json()["autonomy"] == "ask"
    assert not (main.artifacts.root / "user-local").exists() and not (main.artifacts.root / "p1").exists()


# ── Volt: the Export page's receipt ──────────────────────────────────────────

def test_the_receipt_sums_up_the_project_for_the_export_page(client, project, monkeypatch):
    assert client.get("/projects/p1/receipt").json() == {"turns": 0, "takes": 0, "spent_usd": 0.0, "changes": [], "drafts": 0, "render": None}
    done = voiced(client, monkeypatch)
    before = client.get("/projects/p1/receipt").json()
    assert (before["turns"], before["takes"], before["drafts"], before["render"]) == (1, 1, 1, None)
    assert before["spent_usd"] == pytest.approx(client.get("/projects/p1/usage").json()["spent_usd"])
    client.post(f"/projects/p1/plans/{done['plan']['plan_id']}/approve", json={})
    receipt = client.get("/projects/p1/receipt").json()
    assert (receipt["turns"], receipt["takes"], receipt["drafts"]) == (1, 1, 0)
    assert receipt["changes"] == [{"edit_id": "e1", "start": 0.0, "text": "Get 30% off today only.", "kind": "changed", "note": "in Test tone's voice"}]
    render = receipt["render"]
    assert render["filename"] == "ad-voltage.mp4" and len(render["sha256"]) == 64 and render["duration"] > 0 and render["at"]
    assert client.get(f"/projects/p1/artifacts/{render['sha256']}").status_code == 200
    # A removal is a draft until it ships, and never a take; a preview render is not the render.
    removed = client.post("/projects/p1/lines/remove", json={"start": 1.3, "end": 1.8}).json()
    client.post("/projects/p1/export", json={"with_proposals": True})
    again = client.get("/projects/p1/receipt").json()
    assert (again["takes"], again["drafts"], again["render"]["sha256"]) == (1, 1, render["sha256"])
    client.post("/projects/p1/edits/e1/revert")
    client.post(f"/projects/p1/plans/{removed['plan']['plan_id']}/approve", json={})
    assert client.get("/projects/p1/receipt").json()["changes"] == [
        {"edit_id": "e2", "start": 1.3, "text": "", "kind": "removed", "note": "room tone in its place"}]
    assert client.get("/projects/p9/receipt").status_code == 404


def test_a_change_note_says_whose_voice_and_how_it_meets_the_picture(client, project, monkeypatch):
    import app.api.main as main
    from dataclasses import replace
    from app.domain.models import ApprovedEdit
    done = voiced(client, monkeypatch)
    c = main.repo.get_candidate("p1", done["plan"]["items"][0]["candidate"]["candidate_id"])
    edit = lambda **plan: ApprovedEdit(edit_id="x", candidate_id=c.candidate_id, plan=replace(c.plan, **plan), audio=c.audio, frames=c.frames)   # noqa: E731
    notes = {mix: main._change_dict("p1", "local", edit(mix=mix))["note"] for mix in ("replace", "layer", "concatenate", "remove")}
    assert notes == {"replace": "in Test tone's voice", "layer": "Test tone's voice, over the picture",
                     "concatenate": "Test tone's voice, the picture makes room", "remove": "room tone in its place"}
    assert main._change_dict("p1", "local", edit(mix="layer", voice_profile_id="original"))["note"] == "over the picture"
    assert main._change_dict("p1", "local", edit(mix="layer"))["kind"] == "added"
