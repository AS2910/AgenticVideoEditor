import pytest

from app.media import ffmpeg, ingest

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


def test_probe_reports_real_parameters(sample_video):
    probed = ingest.probe_source(sample_video)
    assert probed.duration == pytest.approx(2.3, abs=0.05)
    assert (probed.width, probed.height) == (320, 180)
    assert probed.fps == pytest.approx(25.0, abs=0.01)
    assert probed.has_audio is True


def test_a_video_without_audio_is_taken_and_given_a_silent_track(sample_video_without_audio):
    # Run 5 item 4: no lines to change, but a voice-over can be placed on it.
    probed = ingest.probe_source(sample_video_without_audio)
    assert probed.has_audio is False
    with_sound = ingest.add_silent_audio(sample_video_without_audio, "mp4", probed.duration)
    again = ingest.probe_source(with_sound)
    assert again.has_audio is True
    assert again.duration == pytest.approx(probed.duration, abs=0.1)
    assert (again.width, again.height) == (probed.width, probed.height)


def test_a_file_with_no_video_track_is_refused(sample_audio_only):
    with pytest.raises(ingest.IngestError, match="no video track"):
        ingest.probe_source(sample_audio_only)


def test_a_non_media_file_is_refused(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all")
    with pytest.raises(ingest.IngestError, match="not a video"):
        ingest.probe_source(junk)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(ingest.IngestError):
        ingest.probe_source(tmp_path / "does-not-exist.mp4")


def test_a_video_over_the_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 1.0)
    long_clip = tmp_path / "long.mp4"
    ffmpeg.generate_solid_video(long_clip, 2.0)

    with pytest.raises(ingest.IngestError, match="up to 1 s"):
        ingest.probe_source(long_clip)


def test_a_video_within_the_cap_is_accepted(sample_video, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 5.0)
    assert ingest.probe_source(sample_video).duration == pytest.approx(2.3, abs=0.05)


def test_the_length_check_runs_before_the_audio_check(tmp_path, monkeypatch):
    # An over-long silent clip should complain about length, which is the
    # thing the user can most easily act on.
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 1.0)
    long_silent = tmp_path / "long.mp4"
    ffmpeg.generate_solid_video(long_silent, 2.0)
    with pytest.raises(ingest.IngestError, match="up to 1 s"):
        ingest.probe_source(long_silent)


@pytest.mark.parametrize("rate,expected", [
    ("25/1", 25.0), ("30000/1001", 29.97), ("0/0", 0.0), (None, 0.0), ("bad", 0.0),
])
def test_frame_rate_fractions_are_parsed_safely(rate, expected):
    assert ingest._fps(rate) == pytest.approx(expected, abs=0.01)
