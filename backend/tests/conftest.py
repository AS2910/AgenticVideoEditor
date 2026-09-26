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
