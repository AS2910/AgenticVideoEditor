import pytest

from app.media import ffmpeg

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


def test_generate_silence_writes_a_real_decodable_wav(tmp_path):
    path, duration = ffmpeg.generate_silence(tmp_path / "s.wav", 0.9)
    assert path.is_file() and path.stat().st_size > 0
    assert duration == pytest.approx(0.9, abs=0.05)
    assert ffmpeg.probe(path)["streams"][0]["codec_name"] == "pcm_s16le"


def test_generate_tone_writes_a_real_decodable_wav(tmp_path):
    path, duration = ffmpeg.generate_tone(tmp_path / "t.wav", 0.9, 440)
    assert path.is_file() and path.stat().st_size > 0
    assert duration == pytest.approx(0.9, abs=0.05)
    assert ffmpeg.probe(path)["streams"][0]["codec_name"] == "pcm_s16le"


def test_generate_solid_video_writes_a_real_decodable_mp4(tmp_path):
    path, duration = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 0.9)
    assert path.is_file() and path.stat().st_size > 0
    assert duration == pytest.approx(0.9, abs=0.05)
    assert ffmpeg.probe(path)["streams"][0]["codec_name"] == "h264"


def test_generation_is_byte_identical_across_runs(tmp_path):
    # Content addressing depends on this. If it ever regresses, the artifact
    # store silently stops deduplicating and identical edits stop collapsing.
    a, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 0.5)
    b, _ = ffmpeg.generate_silence(tmp_path / "b.wav", 0.5)
    assert a.read_bytes() == b.read_bytes()

    c, _ = ffmpeg.generate_solid_video(tmp_path / "c.mp4", 0.5)
    d, _ = ffmpeg.generate_solid_video(tmp_path / "d.mp4", 0.5)
    assert c.read_bytes() == d.read_bytes()


def test_different_inputs_produce_different_bytes(tmp_path):
    a, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 0.5)
    b, _ = ffmpeg.generate_silence(tmp_path / "b.wav", 0.9)
    assert a.read_bytes() != b.read_bytes()

    c, _ = ffmpeg.generate_tone(tmp_path / "c.wav", 0.5, 300)
    d, _ = ffmpeg.generate_tone(tmp_path / "d.wav", 0.5, 700)
    assert c.read_bytes() != d.read_bytes()

    e, _ = ffmpeg.generate_solid_video(tmp_path / "e.mp4", 0.5, "0x112233")
    f, _ = ffmpeg.generate_solid_video(tmp_path / "f.mp4", 0.5, "0xaabbcc")
    assert e.read_bytes() != f.read_bytes()


def test_extract_audio_produces_a_mono_wav_for_transcription(tmp_path, sample_video):
    path, duration = ffmpeg.extract_audio(sample_video, tmp_path / "out.wav")

    stream = ffmpeg.probe(path)["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert stream["channels"] == 1
    assert stream["sample_rate"] == "16000"
    assert duration == pytest.approx(2.3, abs=0.1)


def test_extract_audio_from_a_silent_video_raises(tmp_path):
    silent, _ = ffmpeg.generate_solid_video(tmp_path / "silent.mp4", 1.0)
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.extract_audio(silent, tmp_path / "out.wav")


def test_probe_on_a_non_media_file_raises(tmp_path):
    bad = tmp_path / "not-media.wav"
    bad.write_bytes(b"definitely not audio")
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.probe(bad)


def test_missing_binary_raises_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg, "FFPROBE", "ffprobe-that-does-not-exist")
    with pytest.raises(ffmpeg.FFmpegNotInstalled, match="brew install ffmpeg"):
        ffmpeg.probe(tmp_path / "anything.wav")
