"""The real WavLM and UTMOS models on the sample ad. Opt in: AVE_LIVE_MODELS=1
(downloads open weights from Hugging Face / torch.hub on first run)."""
import os
import time
from pathlib import Path

import pytest

from app.media import ffmpeg

pytestmark = pytest.mark.skipif(
    os.environ.get("AVE_LIVE_MODELS") != "1" or not ffmpeg.available(),
    reason="set AVE_LIVE_MODELS=1 (and have ffmpeg) to load the real models",
)

SAMPLE = Path(__file__).parents[3] / "frontend" / "public" / "sample-ad.mp4"


def test_real_models_give_sane_numbers(tmp_path, monkeypatch):
    monkeypatch.delenv("AVE_MEASURE", raising=False)
    from app.continuity import similarity

    assert similarity.available()
    clip, _ = ffmpeg.extract_segment(SAMPLE, tmp_path / "clip.wav", 0.0, 1.2, sample_rate=16000)
    other, _ = ffmpeg.extract_segment(SAMPLE, tmp_path / "other.wav", 1.2, 2.3, sample_rate=16000)

    t = time.time()
    same = similarity.speaker_similarity(clip, clip)
    print(f"\nSIM-o same clip: {same} ({time.time() - t:.1f}s incl. load)")
    t = time.time()
    mos = similarity.naturalness(clip)
    print(f"UTMOS: {mos} ({time.time() - t:.1f}s incl. load)")
    across = similarity.speaker_similarity(clip, other)
    print(f"SIM-o across the clip: {across}")

    assert same is not None and same > 0.99
    assert mos is not None and 1.0 <= mos <= 5.0
