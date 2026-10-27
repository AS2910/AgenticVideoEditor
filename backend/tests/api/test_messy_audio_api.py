"""Run 5 item 8: an upload hears the music or noise under the speech and
separates the voice from it in the background, so a replaced line keeps the bed
and the first export does not wait on Demucs; a clean clip is never separated."""
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.media import ffmpeg
from app.media.stems import Stems
from app.render import compose
from tests.api.test_endpoints import generate, upload
from tests.factories import export_now

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
RATE = compose.OUT_RATE


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_state():
    main.repo.reset()
    main.jobs.reset()
    yield


@pytest.fixture(scope="module")
def music_video(tmp_path_factory):
    """2.3 s of word-like bursts over a chord 12 dB under them."""
    tmp = tmp_path_factory.mktemp("messy")
    n = round(2.3 * RATE)
    rng = np.random.default_rng(4)
    x = np.zeros(n)
    for t in (0.1, 0.8, 1.5):
        i = round(t * RATE)
        x[i:i + round(0.45 * RATE)] = rng.standard_normal(round(0.45 * RATE)) * 0.2
    t = np.arange(n) / RATE
    chord = np.sin(2 * np.pi * 220 * t) + 0.6 * np.sin(2 * np.pi * 277 * t)
    x = x + chord * (0.2 * 10 ** (-12 / 20) / np.sqrt(np.mean(chord ** 2)))
    audio = tmp / "a.wav"
    compose._write(audio, x.astype(np.float32).reshape(-1, 1))
    video, _ = ffmpeg.generate_solid_video(tmp / "v.mp4", 2.3)
    path = tmp / "music.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
                                "-c:v", "copy", "-c:a", "aac", "-shortest", str(path)])
    return path


@pytest.fixture()
def listening(monkeypatch, tmp_path):
    """Upload-time listening on, separation inline and faked; returns the asks."""
    asked = []
    vocals, rest = tmp_path / "v.wav", tmp_path / "r.wav"
    vocals.write_bytes(b"v")
    rest.write_bytes(b"r")
    monkeypatch.setattr(main, "settings", replace(main.settings, stems_on_upload=True))
    monkeypatch.setattr(main, "SEPARATE_IN_BACKGROUND", False)
    monkeypatch.setattr(main.stems_module, "available", lambda: True)
    monkeypatch.setattr(main.stems_module, "separate", lambda wav, out: asked.append(out) or Stems(vocals, rest))
    return asked


def _separations(video_id):
    return [j for j in main.activity.list(video_id) if j.kind == "separate"]


def test_music_under_the_speech_is_separated_after_the_upload(client, music_video, listening):
    assert upload(client, music_video).status_code == 200
    assert main.repo.settings("p1")["bed"]["kind"] == "music"
    jobs = _separations("p1")
    assert len(jobs) == 1 and jobs[0].status == "done"
    assert jobs[0].step_label == "The music stays under new lines"
    assert len(listening) == 1 and listening[0] == main.artifacts.root / "p1" / "stems"


def test_a_clean_clip_is_never_separated(client, sample_video, listening, monkeypatch):
    seen = {}
    real = main.compose
    monkeypatch.setattr(main, "compose", lambda *a, **k: seen.update(stems=k.get("stems", "missing")) or real(*a, **k))
    assert upload(client, sample_video).status_code == 200
    assert main.repo.settings("p1")["bed"]["kind"] == "none"
    assert _separations("p1") == []
    candidate = generate()
    assert client.post("/videos/p1/edits", json={"candidate_id": candidate["candidate_id"]}).status_code == 200
    assert export_now(client, "/videos/p1/export").status_code == 200
    assert listening == [] and seen["stems"] is None      # an edited export of a clean clip skips Demucs


def test_a_failed_separation_never_fails_the_upload(client, music_video, listening, monkeypatch):
    monkeypatch.setattr(main.stems_module, "separate", lambda wav, out: None)
    assert upload(client, music_video).status_code == 200
    job = _separations("p1")[0]
    assert job.status == "failed"
    assert job.error_text == "Could not separate the voice from the music. New lines are mixed over the original sound."


def test_listening_can_be_switched_off(client, music_video, listening, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, stems_on_upload=False))
    assert upload(client, music_video).status_code == 200
    assert "bed" not in main.repo.settings("p1") and _separations("p1") == [] and listening == []
