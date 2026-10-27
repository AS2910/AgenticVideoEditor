"""15c in the compositor: the original's bed under an edit, the original untouched elsewhere."""
import numpy as np
import pytest

from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection
from app.media import ffmpeg
from app.media.stems import Stems
from app.render import compose
from app.render.renderer import render
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
RATE = compose.OUT_RATE
SECONDS = 6.0


def _wave(path, x):
    compose._write(path, x.astype(np.float32).reshape(-1, 1))
    return path


def _voice():
    """Noise bursts with reverberant tails, 6 s: a speaker in a room."""
    rng = np.random.default_rng(1)
    x = np.zeros(round(SECONDS * RATE))
    for t in np.arange(0.2, SECONDS - 0.4, 1.2):
        i = round(t * RATE)
        x[i:i + round(0.3 * RATE)] = rng.standard_normal(round(0.3 * RATE)) * 0.2
    n = round(0.5 * 1.5 * RATE)
    h = rng.standard_normal(n) * 10 ** (-3 * (np.arange(n) / RATE) / 0.5)
    h[0] = 4.0
    size = 1 << (len(x) + n).bit_length()
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[: len(x)] * 0.5


def _bed():
    return 0.1 * np.sin(2 * np.pi * 1000 * np.arange(round(SECONDS * RATE)) / RATE)


@pytest.fixture()
def world(tmp_path):
    voice, bed = _voice(), _bed()
    audio = _wave(tmp_path / "a.wav", voice + bed)
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", SECONDS)
    path = tmp_path / "src.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
                                "-c:v", "copy", "-c:a", "aac", "-shortest", str(path)])
    duration = ffmpeg.duration_of(path)
    source = make_source(media=MediaArtifact("video", "s" * 64, str(path), duration, "mp4"), duration=duration)
    stems = Stems(_wave(tmp_path / "vocals.wav", voice), _wave(tmp_path / "bed.wav", bed))
    return source, stems, tmp_path


def approved(tmp_path, start, end):
    audio, duration = ffmpeg.generate_tone(tmp_path / "e.wav", end - start, 300, sample_rate=24000)
    artifact = MediaArtifact("audio", "e" * 64, str(audio), duration, "wav")
    frames = MediaArtifact("video", "f" * 64, "/nonexistent.mp4", duration, "mp4")
    return ApprovedEdit("e", "c-e", EditPlan(Selection(start, end), "x", "v"), artifact, frames)


def _band(x, hz):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return spec[np.argmin(np.abs(np.fft.rfftfreq(len(x), 1 / RATE) - hz))]


def test_room_is_prepared_only_when_there_is_something_to_match(world, tmp_path):
    source, stems, _ = world
    n = len(compose.decode(source.media.path))
    assert compose.Room.prepare(None, 1, n) is None
    room = compose.Room.prepare(stems, 1, n)
    assert room is not None and room.profile.rt60 == pytest.approx(0.5, rel=0.3)
    # A silent bed falls back.
    silent = Stems(stems.vocals, _wave(tmp_path / "silent.wav", np.zeros(n)))
    assert compose.Room.prepare(silent, 1, n) is None
    # Run 5 item 8: a voice with no tails to read keeps the bed; only the reverb match is skipped.
    mute = Stems(_wave(tmp_path / "mute.wav", np.zeros(n)), stems.accompaniment)
    dry = compose.Room.prepare(mute, 1, n)
    assert dry is not None and dry.profile is None
    assert compose.Room.prepare(Stems(tmp_path / "nope.wav", stems.accompaniment), 1, n) is None


def test_outside_the_edit_is_bit_for_bit_the_original(world):
    source, stems, tmp_path = world
    edit = approved(tmp_path, 2.0, 3.5)
    base = compose.decode(source.media.path)
    room = compose.Room.prepare(stems, base.shape[1], len(base))
    out = compose.splice(base, render(source, [edit]).segments, room)
    i0, i1 = round(2.0 * RATE), round(3.5 * RATE)
    assert out.shape == base.shape
    assert np.array_equal(out[:i0], base[:i0])
    assert np.array_equal(out[i1:], base[i1:])
    assert not np.array_equal(out[i0 + 2000:i1 - 2000], base[i0 + 2000:i1 - 2000])


def test_the_bed_plays_under_the_new_line(world):
    source, stems, tmp_path = world
    edit = approved(tmp_path, 2.0, 3.5)
    base = compose.decode(source.media.path)
    segments = render(source, [edit]).segments
    plain = compose.splice(base, segments)
    room = compose.Room.prepare(stems, 1, len(base))
    out = compose.splice(base, segments, room)
    mid = slice(round(2.3 * RATE), round(3.2 * RATE))
    assert _band(plain[mid, 0], 1000) < 0.05 * _band(base[mid, 0], 1000)   # today's splice drops the bed
    assert _band(out[mid, 0], 1000) == pytest.approx(_band(room.accompaniment[mid, 0], 1000), rel=0.15)
    assert _band(out[mid, 0], 300) > 5 * _band(base[mid, 0], 300)   # and the new line is there


def test_without_stems_compose_is_what_it_was(world, tmp_path):
    source, _, _ = world
    edit = approved(tmp_path, 2.0, 3.5)
    segments = render(source, [edit]).segments
    old = compose.compose(source, segments, tmp_path / "old.mp4")
    none = compose.compose(source, segments, tmp_path / "none.mp4", stems=None)
    assert old.read_bytes() == none.read_bytes()
    base = compose.decode(source.media.path)
    assert np.array_equal(compose.splice(base, segments), compose.splice(base, segments, None))


def test_compose_with_stems_writes_a_playable_file(world, tmp_path):
    source, stems, _ = world
    edit = approved(tmp_path, 2.0, 3.5)
    dest = compose.compose(source, render(source, [edit]).segments, tmp_path / "room.mp4", stems=stems)
    assert ffmpeg.duration_of(dest) == pytest.approx(source.duration, abs=0.1)


def test_a_dry_voice_keeps_the_music_under_a_new_line(world, tmp_path):
    """Run 5 item 8 (evals/messy): a lavalier or voice-over voice has no reverb
    tail, so no room could be read and the bed under a replaced line dropped
    out. The bed now plays on; the take is only EQ'd, not reverberated."""
    source, stems, _ = world
    rng = np.random.default_rng(3)
    dry = np.zeros(round(SECONDS * RATE))
    for t in np.arange(0.2, SECONDS - 0.4, 1.2):   # bursts that stop dead: no tail
        i = round(t * RATE)
        dry[i:i + round(0.3 * RATE)] = rng.standard_normal(round(0.3 * RATE)) * 0.2
    dry_stems = Stems(_wave(tmp_path / "dry.wav", dry), stems.accompaniment)
    edit = approved(tmp_path, 2.0, 3.5)
    base = compose.decode(source.media.path)
    room = compose.Room.prepare(dry_stems, 1, len(base))
    assert room is not None and room.profile is None
    out = compose.splice(base, render(source, [edit]).segments, room)
    mid = slice(round(2.3 * RATE), round(3.2 * RATE))
    assert _band(out[mid, 0], 1000) == pytest.approx(_band(room.accompaniment[mid, 0], 1000), rel=0.15)
    assert _band(out[mid, 0], 300) > 5 * _band(base[mid, 0], 300)

def test_a_take_put_in_the_room_when_it_was_made_is_not_put_there_twice(world):
    """Run 5 item 7: a roomed take keeps the bed under it but gets no second reverb."""
    from dataclasses import replace
    source, stems, tmp_path = world
    edit = approved(tmp_path, 2.0, 3.5)
    roomed = replace(edit, plan=replace(edit.plan, roomed=True))
    base = compose.decode(source.media.path)
    room = compose.Room.prepare(stems, 1, len(base))
    wet = compose.splice(base, render(source, [edit]).segments, room)
    dry = compose.splice(base, render(source, [roomed]).segments, room)
    mid = slice(round(2.3 * RATE), round(3.2 * RATE))
    assert _band(dry[mid, 0], 1000) == pytest.approx(_band(room.accompaniment[mid, 0], 1000), rel=0.15)
    assert not np.allclose(wet[mid, 0], dry[mid, 0])
    take = compose.decode(edit.audio.path)[:, 0]
    # The roomed take is spliced as it was made: the bed plus the take, nothing added.
    expect = room.accompaniment[mid, 0] + take[round(0.3 * RATE):round(0.3 * RATE) + (mid.stop - mid.start)]
    assert np.allclose(dry[mid, 0], expect, atol=2e-3)
