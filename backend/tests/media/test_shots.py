"""Shot boundaries (Phase 16)."""
import pytest

from app.media import ffmpeg, shots

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


def _clip(tmp_path, colors=("red", "blue"), each=1.0):
    parts = []
    for i, c in enumerate(colors):
        parts.append(ffmpeg.generate_solid_video(tmp_path / f"{i}.mp4", each, color=c)[0])
    dest = tmp_path / "cut.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", *[a for p in parts for a in ("-i", str(p))],
        "-filter_complex", "".join(f"[{i}:v]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
    ])
    return dest


def test_a_hard_cut_is_found_at_its_time(tmp_path):
    assert shots.cuts(_clip(tmp_path)) == [1.0]


def test_a_steady_shot_has_no_cuts(tmp_path):
    video, _ = ffmpeg.generate_solid_video(tmp_path / "one.mp4", 2.0)
    assert shots.cuts(video) == []


def test_the_shot_around_a_moment_runs_cut_to_cut():
    assert shots.shot_around(0.5, [1.0, 2.0], 3.0) == (0.0, 1.0)
    assert shots.shot_around(1.0, [1.0, 2.0], 3.0) == (1.0, 2.0)
    assert shots.shot_around(2.5, [1.0, 2.0], 3.0) == (2.0, 3.0)
    assert shots.shot_around(1.5, [], 3.0) == (0.0, 3.0)
