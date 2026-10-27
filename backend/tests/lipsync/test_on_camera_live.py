"""The on-camera look on a real talking face. Opt in: AVE_SYNC_CLIP=<a synced
talking-face clip> (VGG's SyncNet example.avi was used to tune it: 12.7 s, 224x224).

Known limit: the cheap read cannot always tell a dub (a moving mouth under
other speech) from the original; on that clip with its audio reversed two of
three lines still read on camera. That is the safe side (the note shows);
SyncNet in the quality harness is the exact read."""
import os
import subprocess
from pathlib import Path

import pytest

from app.lipsync import on_camera as oc
from app.media import ffmpeg

CLIP = os.environ.get("AVE_SYNC_CLIP")
pytestmark = pytest.mark.skipif(not CLIP or not Path(CLIP or "").exists() or not ffmpeg.available(),
                                reason="set AVE_SYNC_CLIP to a synced talking-face clip")
LINES = [oc.LineSpan(0.5, 4.0), oc.LineSpan(4.0, 8.0), oc.LineSpan(8.0, 12.5)]


def test_a_talking_face_is_on_camera_and_a_still_one_off(tmp_path):
    clip = Path(CLIP)
    assert [v.state for v in oc.detect(clip, LINES)] == [oc.ON] * 3
    still = tmp_path / "still.mp4"
    subprocess.run([ffmpeg.FFMPEG, "-y", "-loglevel", "error", "-ss", "1", "-i", str(clip), "-frames:v", "1",
                    str(tmp_path / "still.png")], check=True)
    subprocess.run([ffmpeg.FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", str(tmp_path / "still.png"),
                    "-i", str(clip), "-map", "0:v", "-map", "1:a", "-t", "12.6", "-r", "25", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(still)], check=True)
    assert [v.state for v in oc.detect(still, LINES)] == [oc.OFF] * 3
