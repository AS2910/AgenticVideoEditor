"""Session-wide test setup.

Imported by pytest before any test module, which matters: `app.api.main` reads
`AVE_DATA_DIR` at import time to build its module-level ArtifactStore. Setting
it here keeps generated media out of the real `backend/var/` tree.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_ARTIFACT_DIR = tempfile.mkdtemp(prefix="ave-tests-")
os.environ["AVE_DATA_DIR"] = _ARTIFACT_DIR

# Blank the key before anything imports the app. `load_dotenv` only ever uses
# setdefault, so this wins over `backend/.env` and keeps the suite on the mock
# transcriber: no network, no spend, no dependence on whose machine it runs on.
os.environ["OPENAI_API_KEY"] = ""
# Same for the paid voice vendor, and dry-run off so tests see the real
# adapter-selection logic rather than whatever the developer's shell set.
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AVE_DRY_RUN"] = ""
# The budgets the tests reason about are the defaults, whatever backend/.env raises them to.
os.environ["AVE_PROJECT_BUDGET_USD"] = "2.0"
os.environ["AVE_USER_BUDGET_USD"] = "10.0"
os.environ["AVE_VOICE_BUDGET_CHARS"] = "2000"
# The measure extra (WavLM, UTMOS) stays off: no model downloads in the suite;
# its tests inject fakes. tests/continuity/test_similarity_live.py opts in.
os.environ["AVE_MEASURE"] = "0"
# A developer's DATABASE_URL never points the suite at their Postgres.
os.environ["DATABASE_URL"] = ""


# The Postgres run (launch, item 6): with AVE_TEST_DATABASE_URL set, every
# `Database` in the suite is a schema in a database made for this session
# (see `app.store.pg.target`), dropped at the end. Unset, the suite is SQLite.
_PG_SERVER = os.environ.get("AVE_TEST_DATABASE_URL")
_PG_DB = None
if _PG_SERVER:
    import psycopg
    from psycopg.conninfo import make_conninfo
    _PG_DB = f"ave_test_{os.getpid()}"
    with psycopg.connect(_PG_SERVER, autocommit=True) as _admin:
        _admin.execute(f'CREATE DATABASE "{_PG_DB}"')
    os.environ["AVE_TEST_DATABASE_URL"] = make_conninfo(_PG_SERVER, dbname=_PG_DB)


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: reads or writes the SQLite file directly; skipped on the Postgres run")


def pytest_collection_modifyitems(config, items):
    if not _PG_DB:
        return
    skip = pytest.mark.skip(reason="reads or writes the SQLite file directly")
    for item in items:
        if item.get_closest_marker("sqlite_only"):
            item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    if not _PG_DB:
        return
    import gc
    import psycopg
    gc.collect()
    try:
        with psycopg.connect(_PG_SERVER, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{_PG_DB}" WITH (FORCE)')
    except Exception:
        pass


# No test reaches a real model, vendor or link host. A test that sets a fake
# key (`anthropic_api_key="k"`) and forgets to swap in a fake client would
# otherwise send a real request; here it fails at once instead. Mocked HTTP
# (httpx.MockTransport, injected clients) never reaches the real transport,
# and the app's own TestClient never leaves the process. The opt-in live
# model test (AVE_LIVE_MODELS=1) is the one exception.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


class RealNetworkInTests(RuntimeError):
    pass


@pytest.fixture(scope="session", autouse=True)
def _no_real_network():
    if os.environ.get("AVE_LIVE_MODELS") == "1":
        yield
        return
    import httpx
    real = httpx.HTTPTransport.handle_request

    def guarded(self, request):
        if request.url.host not in _LOCAL_HOSTS:
            raise RealNetworkInTests(f"a test tried to reach {request.url.host}; mock it")
        return real(self, request)
    httpx.HTTPTransport.handle_request = guarded
    yield
    httpx.HTTPTransport.handle_request = real


@pytest.fixture(scope="session", autouse=True)
def _clean_up_artifacts():
    yield
    shutil.rmtree(_ARTIFACT_DIR, ignore_errors=True)


@pytest.fixture()
def store(tmp_path):
    """A throwaway artifact store, isolated per test."""
    from app.store.artifacts import ArtifactStore
    return ArtifactStore(tmp_path / "artifacts")


def _mux(video: Path, audio: Path, dest: Path) -> Path:
    from app.media import ffmpeg
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest),
    ])
    return dest


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """A real MP4 *with an audio track*, encoded once and shared.

    Ingest refuses silent video now — a dialogue editor has nothing to do with
    it — so the shared upload fixture has to carry audio. 2.3s to match the
    canned transcript, exactly as the bundled `sample-ad.mp4` does.
    """
    from app.media import ffmpeg
    tmp = tmp_path_factory.mktemp("media")
    video, _ = ffmpeg.generate_solid_video(tmp / "silent.mp4", 2.3)
    audio, _ = ffmpeg.generate_silence(tmp / "track.wav", 2.3)
    return _mux(video, audio, tmp / "sample.mp4")


@pytest.fixture(scope="session")
def sample_video_without_audio(tmp_path_factory):
    """A real MP4 carrying no audio stream — ingest must refuse it."""
    from app.media import ffmpeg
    path = tmp_path_factory.mktemp("media") / "silent.mp4"
    ffmpeg.generate_solid_video(path, 1.0)
    return path


@pytest.fixture(scope="session")
def sample_audio_only(tmp_path_factory):
    """A real WAV — a file with no video track, for the rejection path."""
    from app.media import ffmpeg
    path = tmp_path_factory.mktemp("media") / "audio-only.wav"
    ffmpeg.generate_silence(path, 1.0)
    return path


@pytest.fixture(autouse=True)
def _g6_off_unless_asked(monkeypatch):
    """G6 (trust and safety) is on for `local` by default, like every go-live
    flag; the suites written before it run with its gates off by default
    (consent without a read-aloud sentence, exports without a mark), so they
    keep testing what they were written for. A G6 test turns it on with
    `flags.set("golive.g6", "local", True)` (a row always wins)."""
    import sys
    main = sys.modules.get("app.api.main")
    if main is None:
        yield
        return
    original = main.flags._default
    monkeypatch.setattr(main.flags, "_default", lambda flag, owner: False if flag == "golive.g6" else original(flag, owner))
    yield


@pytest.fixture(autouse=True)
def _rate_limits_fresh():
    """Launch item 2: each test starts with empty rate-limit buckets."""
    import sys
    main = sys.modules.get("app.api.main")
    if main is not None and hasattr(main, "rate_limits"):
        main.rate_limits.reset()
    yield
