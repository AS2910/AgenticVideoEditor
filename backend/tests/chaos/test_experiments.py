"""The chaos pass (2026-10-10): the experiments, as tests that run on every push.

Each experiment states a hypothesis about how Voltage behaves when something
around it fails, injects exactly that failure at a seam the code already has,
and checks the steady state it must keep. The ones that failed on the first
run became fixes; the ones that could not be fixed cheaply are documented in
docs/superpowers/plans/2026-10-10-chaos-experiments.md.
"""
import errno
import random
import sqlite3
import threading
import time

import pytest

from app import chaos
from app.adapters.base import VendorError
from app.adapters.elevenlabs import ElevenLabsVoiceAdapter, VoiceError
from app.budget import VoiceBudget
from app.domain.models import EditPlan, Selection
from app.jobs.runner import JobRunner
from app.jobs.store import JobStore
from app.media.ffmpeg import FFmpegNotInstalled
from app.store.artifacts import ArtifactStore
from app.store.db import Database
from app.usage import Ledger
from tests.factories import make_source
from tests.jobs.test_runner import await_job


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app)

PCM = (b"\x00\x10" * 12000)   # half a second of 24 kHz "speech"


def eleven(tmp_path, post, ceiling=1000):
    ledger = Ledger(Database(), ceiling_usd=10.0)
    budget = VoiceBudget(ceiling, ledger=ledger, usd_per_1k=0.3)
    adapter = ElevenLabsVoiceAdapter("key", ArtifactStore(tmp_path), budget, model="m", voice_id="v" * 20, post=post)
    return adapter, budget, ledger


PLAN = EditPlan(Selection(0.0, 0.5), "hello there", "v" * 20, fit="start")


# ── E1 · a rate-limit storm must not spend the budget ───────────────────────────

def test_e1_a_429_storm_leaves_the_budget_and_the_ledger_as_they_were(tmp_path):
    """Hypothesis: a vendor failure costs nothing. Before the fix the charge
    stayed on the ledger — three retries of a 429 ate three takes of budget."""
    faults = chaos.Chaos(chaos.parse("elevenlabs=status:429"), sleep=lambda _: None)
    post = faults.elevenlabs_post(lambda *a: (200, PCM, ""))
    adapter, budget, ledger = eleven(tmp_path, post)
    before = budget.remaining("p1")
    for _ in range(3):
        with pytest.raises(VoiceError):
            adapter.synthesize(make_source(), PLAN)
    assert budget.remaining("p1") == before
    assert faults.hits["elevenlabs"] == 3
    assert ledger.calls_since("p1", "elevenlabs", "2000-01-01") == 0
    assert all(line.calls == 0 for line in ledger.lines("p1"))


def test_e1b_a_connection_reset_refunds_too_and_a_success_still_charges(tmp_path):
    faults = chaos.Chaos(chaos.parse("elevenlabs=reset@0.5"), sleep=lambda _: None, rng=random.Random(1))
    adapter, budget, ledger = eleven(tmp_path, faults.elevenlabs_post(lambda *a: (200, PCM, "")))
    made = failed = spent = 0
    for _ in range(12):
        plan = EditPlan(Selection(0.0, 0.5), f"hello {made}{failed}", "v" * 20, fit="start")
        try:
            adapter.synthesize(make_source(), plan)
            made += 1
            spent += adapter.cost_of(plan)
        except VoiceError:
            failed += 1
    assert made and failed
    assert budget.remaining("p1") == 1000 - spent
    assert ledger.calls_since("p1", "elevenlabs", "2000-01-01") == made


# ── E2 · hung vendor calls fill the pool; /health must show it ──────────────────

def test_e2_two_hung_jobs_fill_the_default_pool_and_the_snapshot_says_so():
    """Hypothesis: with two workers, two hung vendor calls stall every later
    job. True — there is no per-job timeout. The snapshot makes it visible."""
    store = JobStore()
    runner = JobRunner(store, attempts=1, sleep=lambda _: None)
    release = threading.Event()

    def hung(report):
        report(0.2, "Waiting on the vendor")
        release.wait(5)
        return {"ok": True}

    try:
        jobs = [runner.submit(store.create("preview", "p1"), hung) for _ in range(3)]
        deadline = time.time() + 2
        while time.time() < deadline and runner.snapshot()["running"] < 2:
            time.sleep(0.01)
        snap = runner.snapshot()
        assert snap == {"workers": 2, "running": 2, "queued": 1}
        release.set()
        for j in jobs:
            assert await_job(store, j.job_id).status == "succeeded"
        assert runner.snapshot() == {"workers": 2, "running": 0, "queued": 0}
    finally:
        release.set()
        runner.shutdown()


# ── E3 · a restart loses in-flight jobs; the client must learn it, the spend must not vanish ──

def test_e3_a_lost_job_is_a_404_not_a_hang(client):
    resp = client.get("/jobs/job-does-not-exist")
    assert resp.status_code == 404


def test_e3b_the_budget_survives_a_restart_because_it_lives_in_the_database(tmp_path):
    db_path = tmp_path / "ave.db"
    ledger = Ledger(Database(db_path))
    VoiceBudget(1000, ledger=ledger).charge("p1", 300)
    again = VoiceBudget(1000, ledger=Ledger(Database(db_path)))
    assert again.remaining("p1") == 700


# ── E4 · ffmpeg missing or a disk full: the job says what happened ──────────────

def test_e4_a_missing_ffmpeg_fails_the_job_with_a_message_that_names_it():
    store = JobStore()
    runner = JobRunner(store, attempts=1, sleep=lambda _: None)
    try:
        job = runner.submit(store.create("preview", "p1"),
                            lambda report: (_ for _ in ()).throw(FFmpegNotInstalled("'ffmpeg' is not on PATH. Install it with `brew install ffmpeg`.")))
        done = await_job(store, job.job_id)
        assert done.status == "failed"
        assert "ffmpeg" in done.error and "brew install ffmpeg" in done.error
    finally:
        runner.shutdown()


def test_e4b_a_full_disk_fails_the_job_with_the_system_s_own_words():
    store = JobStore()
    runner = JobRunner(store, attempts=1, sleep=lambda _: None)
    try:
        job = runner.submit(store.create("preview", "p1"),
                            lambda report: (_ for _ in ()).throw(OSError(errno.ENOSPC, "No space left on device")))
        done = await_job(store, job.job_id)
        assert done.status == "failed"
        assert "No space left on device" in done.error
    finally:
        runner.shutdown()


# ── E5 · a second process holds the database for a moment ──────────────────────

def test_e5_a_writer_in_another_connection_is_waited_for_not_failed(tmp_path):
    """Hypothesis: a momentary lock from another process (a script, a second
    server) does not fail the request. Before the fix sqlite raised at once."""
    path = tmp_path / "ave.db"
    db = Database(path)
    other = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")

    def release_soon():
        time.sleep(0.4)
        other.execute("COMMIT")
    threading.Thread(target=release_soon).start()
    started = time.time()
    with db.tx() as c:
        c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES ('p1','x','y',1,'u',0,'t')")
    assert 0.3 < time.time() - started < 5.0
    assert db._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


# ── E6 · the fault seam itself: parsing, rates, refusal ────────────────────────

def test_e6_the_spec_is_parsed_and_bad_specs_are_refused():
    faults = chaos.parse("elevenlabs=status:429@0.5; anthropic=hang:30 ;openai=reset")
    assert faults["elevenlabs"] == chaos.Fault("elevenlabs", "status", 429.0, 0.5)
    assert faults["anthropic"] == chaos.Fault("anthropic", "hang", 30.0, 1.0)
    assert faults["openai"] == chaos.Fault("openai", "reset", 0.0, 1.0)
    assert chaos.parse("") == {} and chaos.parse(None) == {}
    for bad in ("elevenlabs", "stripe=status:500", "elevenlabs=status", "elevenlabs=hang", "elevenlabs=explode", "elevenlabs=reset@2"):
        with pytest.raises(ValueError):
            chaos.parse(bad)


def test_e6b_chaos_never_runs_with_sign_in_on_unless_forced():
    assert chaos.from_settings("elevenlabs=reset", "google", force=False) is None
    assert chaos.from_settings("elevenlabs=reset", "google", force=True) is not None
    assert chaos.from_settings("elevenlabs=reset", "off", force=False).describe() == "elevenlabs=reset"
    assert chaos.from_settings(None, "off", force=False) is None


def test_e6c_the_anthropic_wrapper_raises_the_sdk_s_own_errors():
    import anthropic

    class Messages:
        def parse(self, **kw):
            return "fine"

    class Client:
        messages = Messages()

    slept = []
    faults = chaos.Chaos(chaos.parse("anthropic=status:429"), sleep=slept.append)
    with pytest.raises(anthropic.RateLimitError):
        faults.anthropic_client(Client()).messages.parse(model="m")
    faults = chaos.Chaos(chaos.parse("anthropic=hang:30"), sleep=slept.append)
    with pytest.raises(anthropic.APITimeoutError):
        faults.anthropic_client(Client()).messages.parse(model="m")
    assert slept == [30.0]
    faults = chaos.Chaos(chaos.parse("anthropic=slow:2"), sleep=slept.append)
    assert faults.anthropic_client(Client()).messages.parse(model="m") == "fine"
    assert slept == [30.0, 2.0]
    assert chaos.Chaos({}).anthropic_client(Client()).messages.parse(model="m") == "fine"


def test_e6d_the_openai_wrapper_fails_as_the_adapter_expects(tmp_path):
    from app.adapters.openai_whisper import TranscriptionError
    faults = chaos.Chaos(chaos.parse("openai=status:500"))
    with pytest.raises(TranscriptionError):
        faults.openai_post(lambda *a: {"text": "hi"})(tmp_path / "a.wav", "k", 1.0)
    assert issubclass(TranscriptionError, VendorError)   # so the runner retries it


# ── E7 · /health reports the pool and the faults ────────────────────────────────

def test_e7_health_shows_the_pool_and_that_no_chaos_is_on(client):
    body = client.get("/health").json()
    assert body["jobs"] == {"workers": 2, "running": 0, "queued": 0}
    assert body["chaos"] is None
