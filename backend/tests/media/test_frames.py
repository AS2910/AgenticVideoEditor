"""Frames of the picture (UX-5, SV-1): where they are taken from, and that
they are taken once."""
import pytest

from app.media import ffmpeg, frames

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


def test_frame_times_stay_off_the_edges_and_within_the_bounds():
    short = frames.frame_times(7.5)
    assert len(short) == 4                       # one per 2 s, plus one
    assert short[0] == pytest.approx(0.3)
    assert short[-1] == pytest.approx(7.2)
    assert all(b > a for a, b in zip(short, short[1:]))
    assert len(frames.frame_times(1.0)) == 3     # never fewer than three
    assert len(frames.frame_times(120.0)) == 8   # never more than eight
    assert frames.frame_times(0) == []


def test_frames_are_extracted_once_and_reused(tmp_path):
    video, duration = ffmpeg.generate_solid_video(tmp_path / "clip.mp4", 2.3)
    out = tmp_path / "frames"
    first = frames.extract_frames(video, duration, out)
    assert [f.path.name for f in first] == ["frame-00.jpg", "frame-01.jpg", "frame-02.jpg"]
    assert all(f.path.exists() and f.path.stat().st_size > 0 for f in first)
    stamps = [f.path.stat().st_mtime_ns for f in first]
    again = frames.extract_frames(video, duration, out)
    assert [f.path.stat().st_mtime_ns for f in again] == stamps   # nothing re-encoded
    assert [f.at for f in again] == frames.frame_times(duration)
