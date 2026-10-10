"""Real rendering: splice the approved audio into the source and mux an MP4."""
import numpy as np
import pytest

from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection, Transcript, Word
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


# ── Phase 8: layering and inserts ────────────────────────────────────────────

from dataclasses import replace  # noqa: E402


def with_mix(edit, mix):
    return replace(edit, plan=replace(edit.plan, mix=mix))


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2)))


def test_a_layered_edit_keeps_the_original_sound_underneath(source, tmp_path):
    base = compose.decode(source.media.path)
    edit = with_mix(approved(tmp_path, "a", 1.0, 2.0), "layer")
    out = compose.splice(base, render(source, [edit]).segments)
    mid = slice(int(1.4 * RATE), int(1.6 * RATE))
    # Replacing would leave only the edit's tone; layering adds it to the source's.
    expected = base[mid] + compose.decode(edit.audio.path, channels=base.shape[1])[
        int(0.4 * RATE):int(0.6 * RATE)]
    assert np.allclose(out[mid], expected, atol=1e-3)


def test_a_concatenated_edit_takes_no_span_and_becomes_an_insert(source, tmp_path):
    edit = with_mix(approved(tmp_path, "a", 1.0, 2.0), "concatenate")
    manifest = render(source, [edit])
    assert all(s.kind == "original" for s in manifest.segments)
    assert [(i.at, i.edit.edit_id) for i in manifest.inserts] == [(2.0, "a")]


def test_an_insert_pushes_the_rest_of_the_audio_later(source, tmp_path):
    base = compose.decode(source.media.path)
    edit = with_mix(approved(tmp_path, "a", 1.0, 2.0), "concatenate")
    out = compose.insert_audio(base, render(source, [edit]).inserts, source.duration)
    line = int(edit.audio.duration * RATE)
    assert len(out) == len(base) + line
    # What followed the insert point now starts after the line.
    assert np.allclose(out[2 * RATE + line:2 * RATE + line + 100], base[2 * RATE:2 * RATE + 100])


def test_the_export_holds_the_frame_for_an_insert(source, tmp_path):
    edit = with_mix(approved(tmp_path, "a", 1.0, 2.0), "concatenate")
    manifest = render(source, [edit])
    out = compose.compose(source, manifest.segments, tmp_path / "out.mp4", inserts=manifest.inserts)
    streams = {s["codec_type"]: s for s in ffmpeg.probe(out)["streams"]}
    grown = source.duration + edit.audio.duration
    assert float(streams["video"]["duration"]) == pytest.approx(grown, abs=0.1)
    assert float(streams["audio"]["duration"]) == pytest.approx(grown, abs=0.1)


def test_hold_points_at_the_edges_pad_the_first_or_last_piece():
    graph = compose.hold_filter([(0.0, 0.5), (3.0, 1.0)], 3.0)
    assert "start_mode=clone:start_duration=0.500" in graph
    assert "stop_mode=clone:stop_duration=1.000" in graph
    assert "split" not in graph  # one piece: nothing to cut


# ── Phase 16: pieces ─────────────────────────────────────────────────────────────

from app.render import retime  # noqa: E402


def _moving_source(tmp_path, seconds=3.0):
    """A clip whose picture changes every frame, so a frozen frame can be seen."""
    video = tmp_path / "moving.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=25", "-t", f"{seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ])
    audio, _ = ffmpeg.generate_tone(tmp_path / "ma.wav", seconds, 440, sample_rate=RATE)
    path = _mux(video, audio, tmp_path / "msrc.mp4")
    duration = ffmpeg.duration_of(path)
    return make_source(media=MediaArtifact("video", "m" * 64, str(path), duration, "mp4"), duration=duration)


def _frames_identical_runs(path):
    """The longest run of consecutive identical frames in the video."""
    from app.media import motion
    x = motion.frames(path, 0.0, ffmpeg.duration_of(path) + 1)
    longest = run = 1
    for a, b in zip(x, x[1:]):
        run = run + 1 if float(np.abs(a - b).mean()) < 0.5 else 1    # equal but for encoder noise
        longest = max(longest, run)
    return longest


def test_a_flexed_line_stretches_its_picture_and_the_export_grows_by_the_difference(tmp_path):
    source = _moving_source(tmp_path)
    e = approved(tmp_path, "f", 1.0, 2.0)
    from dataclasses import replace as _replace
    audio, duration = ffmpeg.generate_tone(tmp_path / "f-long.wav", 1.1, 300, sample_rate=24000)
    e = _replace(e, plan=_replace(e.plan, flex=1.1), audio=MediaArtifact("audio", "g" * 64, str(audio), duration, "wav"))
    manifest = render(source, [e])
    pieces = retime.tile(source.duration, retime.flex_pieces([e]), 25.0)
    out = compose.compose(source, manifest.segments, tmp_path / "flex.mp4", pieces=pieces, interpolator="none")
    streams = {s["codec_type"]: s for s in ffmpeg.probe(out)["streams"]}
    assert float(streams["video"]["duration"]) == pytest.approx(source.duration + 0.1, abs=0.05)
    assert float(streams["audio"]["duration"]) == pytest.approx(source.duration + 0.1, abs=0.05)
    # The take's audio fills the flexed span and the original follows, shifted by 0.1 s.
    x = compose.decode(out)
    assert dominant_hz(x[int(1.3 * RATE):int(1.9 * RATE), 0]) == pytest.approx(300, abs=5)
    assert dominant_hz(x[int(2.3 * RATE):int(2.9 * RATE), 0]) == pytest.approx(440, abs=5)


def test_a_living_hold_makes_room_without_a_frozen_frame(tmp_path):
    source = _moving_source(tmp_path)
    edit = with_mix(approved(tmp_path, "a", 1.0, 1.5), "concatenate")    # a 0.5 s line added after 1.5
    manifest = render(source, [edit])
    words = Transcript(words=(Word("x", 1.0, 1.5), Word("y", 2.2, 2.6)))
    living = retime.living_pieces(manifest.inserts, words, source.duration)
    pieces = retime.tile(source.duration, living, 25.0)
    assert [p.kind for p in pieces] == ["copy", "living", "copy"] and retime.held_seconds(pieces) == 0.0
    out = compose.compose(source, manifest.segments, tmp_path / "living.mp4", pieces=pieces, interpolator="none")
    streams = {s["codec_type"]: s for s in ffmpeg.probe(out)["streams"]}
    grown = source.duration + edit.audio.duration
    assert float(streams["video"]["duration"]) == pytest.approx(grown, abs=0.05)
    assert float(streams["audio"]["duration"]) == pytest.approx(grown, abs=0.05)
    # The stretched pause repeats frames at most as far as its slowest chunk; the old hold froze 12 of them.
    assert _frames_identical_runs(out) <= 2
    # The added line plays right after its point, over the room's own sound; the original resumes after.
    x = compose.decode(out)
    assert dominant_hz(x[int(1.55 * RATE):int(1.95 * RATE), 0]) == pytest.approx(300, abs=5)
    assert dominant_hz(x[int(2.6 * RATE):int(3.3 * RATE), 0]) == pytest.approx(440, abs=5)


def test_the_old_hold_still_freezes_when_asked_for(tmp_path):
    source = _moving_source(tmp_path)
    edit = with_mix(approved(tmp_path, "a", 1.0, 1.5), "concatenate")
    manifest = render(source, [edit])
    out = compose.compose(source, manifest.segments, tmp_path / "held.mp4", inserts=manifest.inserts)
    assert _frames_identical_runs(out) >= 4    # 0.5 s held, sampled at 10 fps


def test_the_video_graph_counts_whole_frames_and_loops_a_short_pause():
    piece = retime.Piece(1.0, 1.6, 1.4, "living", (retime.Chunk(1.0, 1.3, 1.6), retime.Chunk(1.3, 1.6, 1.6)), loops=2)
    graph = compose.video_graph(retime.tile(3.0, [piece], 25.0), 25.0, "none")
    assert "fps=25,split=3" in graph
    assert "trim=start_frame=0:end_frame=25" in graph           # the copy before, by frames
    assert "setpts=(PTS-STARTPTS)*1.600000,fps=25" in graph      # the stretch, frames repeated
    assert "reverse" in graph and "concat=n=2:v=1:a=0,trim=end_frame=35" in graph   # two passes, 1.4 s
    assert graph.endswith("concat=n=3:v=1:a=0,setpts=N/(25*TB)[v]")
    assert "minterpolate" in compose.interpolation("minterpolate", 25.0)
    assert "minterpolate" in compose.interpolation("rife", 25.0)   # the seam falls back
