"""Real rendering: splice the approved audio into the source and mux an MP4."""
import numpy as np
import pytest

from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection
from app.media import ffmpeg
from app.render import compose
from app.render.renderer import render
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
RATE = compose.OUT_RATE


def _mux(video, audio, dest):
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest),
    ])
    return dest


@pytest.fixture()
def source(tmp_path):
    """A 3 s H.264 video whose soundtrack is a steady 440 Hz tone."""
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 3.0)
    audio, _ = ffmpeg.generate_tone(tmp_path / "a.wav", 3.0, 440, sample_rate=RATE)
    path = _mux(video, audio, tmp_path / "src.mp4")
    duration = ffmpeg.duration_of(path)
    media = MediaArtifact("video", "s" * 64, str(path), duration, "mp4")
    return make_source(media=media, duration=duration)


def approved(tmp_path, edit_id, start, end, freq=300):
    audio, duration = ffmpeg.generate_tone(tmp_path / f"{edit_id}.wav", end - start, freq, sample_rate=24000)
    artifact = MediaArtifact("audio", edit_id * 32, str(audio), duration, "wav")
    frames = MediaArtifact("video", "f" * 64, "/nonexistent.mp4", duration, "mp4")
    return ApprovedEdit(edit_id, f"c-{edit_id}", EditPlan(Selection(start, end), "x", "v"), artifact, frames)


def dominant_hz(x):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return np.fft.rfftfreq(x.size, 1 / RATE)[np.argmax(spectrum)]


# ── splice ────────────────────────────────────────────────────────────────────

def test_the_edit_replaces_its_span_and_the_rest_is_untouched(source, tmp_path):
    e1 = approved(tmp_path, "e1", 1.0, 2.0)
    base = compose.decode(source.media.path)
    out = compose.splice(base, render(source, [e1]).segments)

    assert out.shape == base.shape
    inside = out[int(1.1 * RATE):int(1.9 * RATE), 0]
    assert dominant_hz(inside) == pytest.approx(300, abs=5)
    # Bit-identical outside the edit (the crossfade stays inside the span).
    assert np.array_equal(out[: int(1.0 * RATE)], base[: int(1.0 * RATE)])
    assert np.array_equal(out[int(2.0 * RATE):], base[int(2.0 * RATE):])


def test_seams_are_crossfaded_not_cut(source, tmp_path):
    e1 = approved(tmp_path, "e1", 1.0, 2.0)
    base = compose.decode(source.media.path)
    out = compose.splice(base, render(source, [e1]).segments)[:, 0]
    # A hard cut between two tones jumps by up to twice the amplitude in one
    # sample; a crossfade keeps every step as small as the tones' own slopes.
    typical = np.max(np.abs(np.diff(base[: RATE, 0])))
    for seam in (1.0, 2.0):
        i = int(seam * RATE)
        window = out[i - 2000:i + 2000]
        assert np.max(np.abs(np.diff(window))) <= typical * 1.5


def test_a_trimmed_edit_uses_the_right_part_of_its_audio(source, tmp_path):
    # e1's audio is 300 Hz then 600 Hz; e2 takes e1's first half, so what
    # survives of e1 must be its *second* half — the 600 Hz part.
    first, _ = ffmpeg.generate_tone(tmp_path / "p1.wav", 0.5, 300, sample_rate=24000)
    second, _ = ffmpeg.generate_tone(tmp_path / "p2.wav", 0.5, 600, sample_rate=24000)
    joined = tmp_path / "e1.wav"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(first), "-i", str(second),
                                "-filter_complex", "concat=n=2:v=0:a=1", str(joined)])
    e1 = ApprovedEdit("e1", "c", EditPlan(Selection(1.0, 2.0), "x", "v"),
                      MediaArtifact("audio", "1" * 64, str(joined), 1.0, "wav"),
                      MediaArtifact("video", "f" * 64, "/x", 1.0, "mp4"))
    e2 = approved(tmp_path, "e2", 1.0, 1.5, freq=200)
    out = compose.splice(compose.decode(source.media.path), render(source, [e1, e2]).segments)
    assert dominant_hz(out[int(1.1 * RATE):int(1.4 * RATE), 0]) == pytest.approx(200, abs=5)
    assert dominant_hz(out[int(1.6 * RATE):int(1.9 * RATE), 0]) == pytest.approx(600, abs=5)


def test_stereo_sources_keep_both_channels(tmp_path):
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 2.0)
    stereo = tmp_path / "st.wav"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                f"sine=frequency=440:sample_rate={RATE}", "-t", "2", "-ac", "2", str(stereo)])
    path = _mux(video, stereo, tmp_path / "st.mp4")
    assert compose.decode(path).shape[1] == 2


# ── the rendered file ─────────────────────────────────────────────────────────

def test_render_writes_a_playable_mp4_the_length_of_the_source(source, tmp_path):
    e1 = approved(tmp_path, "e1", 1.0, 2.0)
    out = compose.compose(source, render(source, [e1]).segments, tmp_path / "out.mp4")

    info = ffmpeg.probe(out)
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["codec_name"] == "h264"
    assert kinds["audio"]["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(source.duration, abs=0.05)
    heard = compose.decode(out)[int(1.2 * RATE):int(1.8 * RATE), 0]
    assert dominant_hz(heard) == pytest.approx(300, abs=5)


def test_an_h264_source_is_stream_copied(source, tmp_path):
    out = compose.compose(source, render(source, []).segments, tmp_path / "copy.mp4")
    src_frames = int(ffmpeg.probe(source.media.path)["streams"][0]["nb_frames"])
    video = next(s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video")
    assert int(video["nb_frames"]) == src_frames


def test_a_non_h264_source_is_re_encoded_so_it_plays_everywhere(tmp_path):
    raw = tmp_path / "mpeg4.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25",
                                "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={RATE}",
                                "-t", "1.5", "-c:v", "mpeg4", "-c:a", "aac", str(raw)])
    media = MediaArtifact("video", "m" * 64, str(raw), 1.5, "mp4")
    src = make_source(media=media, duration=ffmpeg.duration_of(raw))
    out = compose.compose(src, render(src, []).segments, tmp_path / "out.mp4")
    video = next(s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264"
