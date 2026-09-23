from pathlib import Path

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


# --- Phase 4a: vendor audio in, fitted to the span --------------------------

from app.errors import NonRetryableError  # noqa: E402

FIXTURE_PCM = Path(__file__).parents[1] / "fixtures" / "elevenlabs-tts.pcm"


def test_pcm_to_wav_wraps_raw_samples_as_a_real_wav(tmp_path):
    pcm = FIXTURE_PCM.read_bytes()
    path, duration = ffmpeg.pcm_to_wav(pcm, tmp_path / "v.wav", sample_rate=24000)

    stream = ffmpeg.probe(path)["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert int(stream["sample_rate"]) == 24000
    assert stream["channels"] == 1
    assert duration == pytest.approx(len(pcm) / 2 / 24000, abs=0.01)


def test_pcm_to_wav_refuses_an_empty_response(tmp_path):
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.pcm_to_wav(b"", tmp_path / "v.wav", sample_rate=24000)


@pytest.mark.parametrize("target", [1.0 / 1.25 + 0.01, 1.0 / 0.8 - 0.01, 1.0])
def test_fit_duration_lands_on_the_target(tmp_path, target):
    src, _ = ffmpeg.generate_tone(tmp_path / "in.wav", 1.0, 440)
    path, duration = ffmpeg.fit_duration(src, tmp_path / "out.wav", target)
    assert duration == pytest.approx(target, rel=0.02)
    assert ffmpeg.duration_of(path) == pytest.approx(target, rel=0.02)


def test_a_slightly_short_line_is_slowed_then_centred_in_silence(tmp_path):
    # 1.0 s of speech into 1.4 s: slowed to the 0.8 floor (1.25 s), then
    # 0.075 s of silence either side.
    src, _ = ffmpeg.generate_tone(tmp_path / "in.wav", 1.0, 440)
    path, duration = ffmpeg.fit_duration(src, tmp_path / "out.wav", 1.4)
    assert duration == pytest.approx(1.4, abs=0.01)
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
    lead, middle, tail = x[: int(0.06 * rate)], x[int(0.3 * rate):int(1.1 * rate)], x[-int(0.06 * rate):]
    assert np.max(np.abs(lead)) == 0 and np.max(np.abs(tail)) == 0
    assert np.sqrt(np.mean(middle ** 2)) > 1000


@pytest.mark.parametrize("target", [0.5, 3.0])
def test_fit_duration_refuses_a_stretch_that_would_sound_wrong(tmp_path, target):
    # 0.5: would need 2x speed-up. 3.0: even slowed, speech fills under 60%.
    src, _ = ffmpeg.generate_tone(tmp_path / "in.wav", 1.0, 440)
    with pytest.raises(ffmpeg.SpanMismatch) as err:
        ffmpeg.fit_duration(src, tmp_path / "out.wav", target)
    assert err.value.natural == pytest.approx(1.0, abs=0.01)
    assert err.value.target == target
    assert isinstance(err.value, NonRetryableError)
    assert "selection" in str(err.value)  # tells the user what to change


def test_extract_segment_cuts_the_requested_span(tmp_path):
    src, _ = ffmpeg.generate_tone(tmp_path / "in.wav", 2.0, 440)
    path, duration = ffmpeg.extract_segment(src, tmp_path / "cut.wav", 0.5, 1.25)
    assert duration == pytest.approx(0.75, abs=0.02)
    assert ffmpeg.probe(path)["streams"][0]["channels"] == 1
