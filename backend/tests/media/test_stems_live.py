"""Runs the real htdemucs model once. Opt in with AVE_LIVE_MODELS=1 (first run downloads weights)."""
import os

import numpy as np
import pytest

from app.media import ffmpeg, stems
from app.render import compose

pytestmark = [
    pytest.mark.skipif(os.environ.get("AVE_LIVE_MODELS") != "1", reason="set AVE_LIVE_MODELS=1 to run the real model"),
    pytest.mark.skipif(not (ffmpeg.available() and stems.available()), reason="needs ffmpeg and demucs"),
]


def test_demucs_separates_a_short_clip(tmp_path):
    wav, _ = ffmpeg.generate_tone(tmp_path / "clip.wav", 8.0, 440, sample_rate=44100)
    result = stems.separate(wav, tmp_path / "cache")
    assert result is not None
    original = compose.decode(wav, channels=1)
    for part in (result.vocals, result.accompaniment):
        audio = compose.decode(part, channels=1)
        assert abs(len(audio) - len(original)) < compose.OUT_RATE // 10
        assert np.isfinite(audio).all()
    # The two stems add back up to roughly the input.
    n = min(len(original), len(compose.decode(result.vocals, channels=1)))
    total = compose.decode(result.vocals, channels=1)[:n] + compose.decode(result.accompaniment, channels=1)[:n]
    assert np.abs(total - original[:n]).mean() < 0.05
