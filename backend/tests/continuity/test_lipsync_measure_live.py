"""The real SyncNet on the sample ad's talking shopkeeper. Opt in: AVE_LIVE_MODELS=1
(downloads the open syncnet_v2.model weights, ~55 MB, on first run)."""
import os
import time
from pathlib import Path

import pytest

from app.media import ffmpeg

pytestmark = pytest.mark.skipif(
    os.environ.get("AVE_LIVE_MODELS") != "1" or not ffmpeg.available(),
    reason="set AVE_LIVE_MODELS=1 (and have ffmpeg) to load the real model",
)

# A reference clip with a face in sync (VGG's own example, 224x224, 12.7 s): LSE-D
# about 5.3, LSE-C about 10, offset +3. Set AVE_SYNC_CLIP to its path to run this.
CLIP = os.environ.get("AVE_SYNC_CLIP")


@pytest.mark.skipif(not CLIP or not Path(CLIP or "").exists(), reason="set AVE_SYNC_CLIP to a synced talking-face clip")
def test_real_syncnet_reads_a_synced_clip_as_synced_and_a_delayed_one_as_not(tmp_path, monkeypatch):
    monkeypatch.delenv("AVE_MOUTH_MEASURE", raising=False)
    from app.continuity import lipsync_measure as lm

    assert lm.available()
    clip = Path(CLIP)
    t = time.time()
    synced = lm.lse(clip)
    print(f"\nsynced: {synced} ({time.time() - t:.1f}s incl. load)")
    audio = tmp_path / "late.wav"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000",
                                "-af", "adelay=1000", str(audio)])
    late = lm.lse(clip, audio)
    print(f"audio +1.0 s: {late}")

    assert synced is not None and late is not None
    assert synced.distance < 7 and synced.confidence > 5 and abs(synced.offset_frames) <= 4
    assert late.distance > synced.distance + 3
    assert lm.lip_sync_score(late, synced) == 0.0
