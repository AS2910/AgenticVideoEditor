"""Moving the mouth in the export (Phase 17b/c). The vendor is a fake that
returns a flat red clip as long as it was asked for, so what is checked is
what Voltage does with it: what it sends, what it pays, and the picture it makes."""
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.sync_so import MouthConfigError, MouthError, MouthRefused
from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection
from app.media import faces, ffmpeg
from app.render.mouth import MouthRenderer, patch_video
from app.render.renderer import RenderSegment
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")

FPS = 30


def solid(path: Path, colour: str, seconds: float, audio: bool = False) -> Path:
    args = ["-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r={FPS}:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:d={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run([ffmpeg.FFMPEG, "-y", "-loglevel", "error", *args, "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def pixel(path: Path, at: float) -> tuple[int, int, int]:
    raw = subprocess.run([ffmpeg.FFMPEG, "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(path),
                          "-frames:v", "1", "-vf", "scale=1:1,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


def frames_of(path: Path) -> int:
    out = subprocess.run([ffmpeg.FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


@pytest.fixture()
def source_video(tmp_path):
    return solid(tmp_path / "source.mp4", "blue", 2.0, audio=True)


# --- the picture patch ---------------------------------------------------------

def test_a_stretch_of_the_picture_is_replaced_frame_for_frame_and_the_rest_is_untouched(tmp_path, source_video):
    from app.render.mouth import Moved
    red = solid(tmp_path / "red.mp4", "red", 0.6)
    out = patch_video(source_video, [Moved("e1", 0.5, 1.1, "lipsync-2", 0.0, True, red)], tmp_path / "patched.mp4")
    assert frames_of(out) == frames_of(source_video)                    # nothing gained or lost
    r, g, b = pixel(out, 0.8)
    assert r > 200 and b < 80                                            # red inside the stretch
    for t in (0.2, 1.5):
        r, g, b = pixel(out, t)
        assert b > 150 and r < 80                                        # blue before and after
    assert ffmpeg.probe(out)["streams"][1]["codec_type"] == "audio"      # the soundtrack comes through


def test_a_clip_a_frame_short_is_padded_not_dropped(tmp_path, source_video):
    from app.render.mouth import Moved
    short = solid(tmp_path / "short.mp4", "red", 0.5667)                 # 17 frames for an 18-frame stretch
    out = patch_video(source_video, [Moved("e1", 0.5, 1.1, "lipsync-2", 0.0, True, short)], tmp_path / "p.mp4")
    assert frames_of(out) == frames_of(source_video)
    assert pixel(out, 1.05)[0] > 200                                     # the last frame of the stretch (at 1.067 s) is still red


def test_two_stretches_patch_independently(tmp_path, source_video):
    from app.render.mouth import Moved
    red, green = solid(tmp_path / "r.mp4", "red", 0.4), solid(tmp_path / "g.mp4", "lime", 0.4)
    out = patch_video(source_video, [
        Moved("e2", 1.3, 1.7, "lipsync-2", 0, True, green), Moved("e1", 0.2, 0.6, "lipsync-2", 0, True, red),
    ], tmp_path / "p.mp4")
    assert pixel(out, 0.4)[0] > 200 and pixel(out, 1.5)[1] > 150 and pixel(out, 1.0)[2] > 150


# --- what is sent, paid and kept -----------------------------------------------

class FakeClient:
    def __init__(self, tmp_path, fail=None, estimate=0.08):
        self.tmp, self.fail, self._estimate = tmp_path, fail, estimate
        self.sent: list[tuple[float, str, dict | None]] = []

    def estimate(self, model, seconds):
        return self._estimate

    def move_mouth(self, clip, audio, dest, *, model, options=None):
        if self.fail:
            raise self.fail
        seconds = ffmpeg.duration_of(clip)
        self.sent.append((round(seconds, 2), model, options))
        solid(Path(dest), "red", seconds)
        return Path(dest), {"status": "COMPLETED"}


@pytest.fixture()
def world(tmp_path, source_video):
    media = MediaArtifact("video", "s" * 64, str(source_video), 2.0, "mp4")
    source = make_source(project_id="p1", media=media, duration=2.0)
    wav, duration = ffmpeg.generate_tone(tmp_path / "take.wav", 1.0, 220)
    audio = MediaArtifact("audio", "a" * 64, str(wav), duration, "wav")
    plan = EditPlan(Selection(0.4, 1.4), "hi", "v", mix="replace")
    edit = ApprovedEdit("e1", "c1", plan, audio, audio)
    seg = RenderSegment(0.4, 1.4, "edited", "a" * 64, audio, edit)
    return source, edit, seg


def renderer(tmp_path, client, found, **kw):
    return MouthRenderer(client, tmp_path / "cache", stretches=lambda *a, **k: found, **kw)


def test_only_the_stretches_with_a_face_are_sent_and_paid_for(tmp_path, world):
    source, edit, seg = world
    client = FakeClient(tmp_path)
    spent = []
    r = renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 1)], record=lambda usd, s, m: spent.append((usd, round(s, 2), m)))
    result = r.apply(source, [seg], [])
    assert [(round(m.start, 2), round(m.end, 2)) for m in result.moved] == [(0.6, 1.2)]
    assert client.sent == [(0.6, "lipsync-2", None)]                    # 0.6 s of 2.0 s, not the whole clip
    assert spent == [(0.08, 0.6, "lipsync-2")]
    assert result.seconds == pytest.approx(0.6) and result.usd == pytest.approx(0.08)


def test_a_stretch_is_made_once_per_take_and_then_comes_from_the_cache(tmp_path, world):
    source, edit, seg = world
    client, spent = FakeClient(tmp_path), []
    r = renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 1)], record=lambda *a: spent.append(a))
    first = r.apply(source, [seg], [])
    second = r.apply(source, [seg], [])
    assert len(client.sent) == 1 and len(spent) == 1                    # exporting again costs nothing
    assert second.moved[0].cached and second.usd == 0 and not first.moved[0].cached


def test_a_different_take_is_a_different_stretch(tmp_path, world):
    source, edit, seg = world
    client = FakeClient(tmp_path)
    r = renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 1)])
    r.apply(source, [seg], [])
    other = replace(edit, audio=replace(edit.audio, sha256="b" * 64))
    r.apply(source, [replace(seg, edit=other)], [])
    assert len(client.sent) == 2


def test_a_voice_over_a_reverted_edit_and_an_unedited_span_are_not_sent(tmp_path, world):
    source, edit, seg = world
    client = FakeClient(tmp_path)
    r = renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 1)])
    layered = replace(edit, plan=replace(edit.plan, mix="layer"))
    reverted = replace(edit, reverted=True)
    r.apply(source, [replace(seg, edit=layered), replace(seg, edit=reverted),
                     RenderSegment(0.0, 0.4, "original", "ad.mp4")], [])
    assert client.sent == []


def test_a_span_with_no_face_sends_nothing(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path)
    result = renderer(tmp_path, client, []).apply(source, [seg], [])
    assert client.sent == [] and result.moved == () and result.notes == ()


def test_more_than_one_face_asks_the_vendor_to_find_who_is_speaking(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path)
    renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 2)]).apply(source, [seg], [])
    assert client.sent[0][2] == {"active_speaker_detection": {"auto_detect": True}}


def test_a_stretch_over_the_spending_limit_is_skipped_with_a_reason(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path)
    result = renderer(tmp_path, client, [faces.Stretch(0.6, 1.2, 1)], afford=lambda usd: False).apply(source, [seg], [])
    assert client.sent == [] and result.moved == ()
    assert "spending limit" in result.notes[0]


def test_a_refused_stretch_keeps_its_picture_and_the_next_one_is_still_tried(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path, fail=MouthRefused("no_face", "No face was found in the clip."))
    result = renderer(tmp_path, client, [faces.Stretch(0.5, 0.9, 1), faces.Stretch(1.0, 1.4, 1)]).apply(source, [seg], [])
    assert result.moved == () and len(result.notes) == 2
    assert "No face was found" in result.notes[0]


def test_a_key_or_plan_problem_stops_further_calls(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path, fail=MouthConfigError("The sync.so plan has no credit left for this clip."))
    result = renderer(tmp_path, client, [faces.Stretch(0.5, 0.9, 1), faces.Stretch(1.0, 1.4, 1)]).apply(source, [seg], [])
    assert result.moved == () and len(result.notes) == 1               # not one doomed call per stretch
    assert "no credit left" in result.notes[0]


def test_a_vendor_outage_does_not_fail_the_export(tmp_path, world):
    source, _, seg = world
    result = renderer(tmp_path, FakeClient(tmp_path, fail=MouthError("down")), [faces.Stretch(0.6, 1.2, 1)]).apply(source, [seg], [])
    assert result.moved == () and "unavailable" in result.notes[0]


def test_the_patched_picture_carries_the_moved_stretch(tmp_path, world):
    source, _, seg = world
    r = renderer(tmp_path, FakeClient(tmp_path), [faces.Stretch(0.6, 1.2, 1)])
    result = r.patch(source, r.apply(source, [seg], []), tmp_path / "patched.mp4")
    assert result.video and pixel(result.video, 0.9)[0] > 200 and pixel(result.video, 0.2)[2] > 150


def test_the_spending_limit_counts_everything_already_committed_in_the_same_export(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path, estimate=0.08)
    found = [faces.Stretch(0.5, 0.9, 1), faces.Stretch(1.0, 1.4, 1)]
    result = renderer(tmp_path, client, found, afford=lambda total: total <= 0.10).apply(source, [seg], [])
    assert [round(m.start, 1) for m in result.moved] == [0.5]          # the second would take it to 0.16
    assert len(client.sent) == 1 and "spending limit" in result.notes[0]


def test_several_stretches_are_all_made_and_come_back_in_order(tmp_path, world):
    source, _, seg = world
    client = FakeClient(tmp_path)
    found = [faces.Stretch(0.5, 0.8, 1), faces.Stretch(0.9, 1.2, 1), faces.Stretch(1.25, 1.4, 1)]
    result = renderer(tmp_path, client, found).apply(source, [seg], [])
    assert [round(m.start, 2) for m in result.moved] == [0.5, 0.9, 1.25] and len(client.sent) == 3
