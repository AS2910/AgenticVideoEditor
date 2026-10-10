"""How much the picture moves (Phase 16)."""
import pytest

from app.media import ffmpeg, motion

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


def _moving(tmp_path, seconds=2.0):
    dest = tmp_path / "moving.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=160x90:r=25", "-t", f"{seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
    ])
    return dest


def test_a_still_picture_reads_as_no_motion(tmp_path):
    video, _ = ffmpeg.generate_solid_video(tmp_path / "still.mp4", 1.0)
    m = motion.motion(video, 0.0, 1.0)
    assert len(m) == motion.chunk_count(1.0) == 4
    assert all(v == 0.0 for v in m)


def test_a_moving_picture_reads_as_motion_in_every_chunk(tmp_path):
    m = motion.motion(_moving(tmp_path), 0.5, 1.5)
    assert len(m) == 4 and all(v > 0.0 for v in m)


def test_too_short_a_window_gives_zeros_not_an_error(tmp_path):
    video, _ = ffmpeg.generate_solid_video(tmp_path / "still.mp4", 1.0)
    assert motion.motion(video, 0.0, 0.05) == [0.0]


def test_chunk_count_rounds_up():
    assert motion.chunk_count(0.25) == 1
    assert motion.chunk_count(0.26) == 2
    assert motion.chunk_count(1.0) == 4
