"""Run 5, item 10: who is seen saying each line. The face finder and the
frames are fakes here; the live check on a real talking face is opt-in
(test_on_camera_live.py)."""
import numpy as np
import pytest

from app.lipsync import on_camera as oc
from app.media import ffmpeg

FPS = oc.SAMPLE_FPS


def test_no_face_for_the_line_is_off_camera():
    v = oc.judge(oc.LineSpan(0, 2), frames=25, with_face=2, mouth=[], head=[], level_change=[])
    assert v.state == oc.OFF and v.why == "No face on screen for this line."


def test_a_face_whose_mouth_moves_with_the_sound_is_on_camera():
    level = [abs(np.sin(i)) * 6 for i in range(20)]
    mouth = [x / 6 + 0.3 for x in level]           # moves with the sound, more than the head
    v = oc.judge(oc.LineSpan(0, 2), 25, 24, mouth, [0.2] * 20, level)
    assert v.state == oc.ON and v.sync > 0.9 and v.activity > 1.15


def test_a_face_with_a_still_mouth_is_off_camera():
    v = oc.judge(oc.LineSpan(0, 2), 25, 25, [0.1] * 20, [0.2] * 20, [3.0] * 20)
    assert v.state == oc.OFF and "still" in v.why


def test_a_mouth_that_moves_but_not_with_the_sound_is_unsure():
    mouth = [0.5 + abs(np.sin(i)) for i in range(20)]
    v = oc.judge(oc.LineSpan(0, 2), 25, 25, mouth, [0.2] * 20, [3.0] * 20)   # the sound does not change with it
    assert v.state == oc.UNSURE


def test_a_face_part_of_the_time_is_unsure():
    level = [abs(np.sin(i)) * 6 for i in range(10)]
    v = oc.judge(oc.LineSpan(0, 2), 25, 10, [x / 6 + 0.3 for x in level], [0.2] * 10, level)
    assert v.state == oc.UNSURE


def test_best_corr_finds_a_two_frame_lag():
    a = np.sin(np.arange(40) / 2.0)
    assert oc.best_corr(a[2:], a[:-2]) > 0.99


def _face_frames(seconds, open_at):
    """Frames at the sample rate: a grey face-sized block with a mouth patch that is
    dark (open) at the times `open_at` says."""
    out = []
    for k in range(int(seconds * FPS)):
        t = k / FPS
        f = np.full((360, 640, 3), 120, np.uint8)
        f[60:300, 200:440] = 180
        f[120:140, 260:300] = 40                      # eyes
        f[120:140, 340:380] = 40
        if open_at(t):
            f[228:262, 280:360] = 20                  # an open mouth
        else:
            f[240:246, 280:360] = 60                  # a closed one
        out.append((t, f))
    return out


FACE = (200.0, 60.0, 240.0, 240.0, 285.0, 240.0, 355.0, 240.0, 280.0, 130.0, 360.0, 130.0)


def test_detect_reads_each_line_from_the_frames_it_is_given():
    talking = lambda t: round(t * FPS) % 3 != 0       # opens and closes about four times a second
    frames = _face_frames(4.0, talking)
    levels = np.array([-20.0 if talking(k / FPS) else -45.0 for k in range(len(frames))])
    # The face is there for the first two seconds only.
    find = lambda f: FACE if f[100, 300, 0] == 180 else None
    for t, f in frames:
        if t >= 2.0:
            f[:] = 90
    lines = [oc.LineSpan(0.1, 1.9), oc.LineSpan(2.1, 3.9)]
    out = oc.detect("unused.mp4", lines, frames=frames, levels=levels, find=find)
    assert [v.state for v in out] == [oc.ON, oc.OFF]


def test_without_the_face_finder_every_line_is_unsure(monkeypatch):
    monkeypatch.setattr(oc, "available", lambda: False)
    out = oc.detect("unused.mp4", [oc.LineSpan(0, 1)])
    assert out[0].state == oc.UNSURE


def test_state_for_takes_the_line_that_covers_most_of_the_span():
    record = {"status": "done", "lines": [
        {"start": 0.0, "end": 2.0, "state": "on_camera"}, {"start": 2.0, "end": 5.0, "state": "off_camera"}]}
    assert oc.state_for(record, 0.2, 1.8) == "on_camera"
    assert oc.state_for(record, 1.5, 4.0) == "off_camera"
    assert oc.state_for({"status": "running", "lines": []}, 0, 1) is None
    assert oc.state_for(None, 0, 1) is None


@pytest.mark.skipif(not ffmpeg.available() or not oc.available(), reason="needs ffmpeg and OpenCV")
def test_a_real_clip_with_no_face_is_off_camera_everywhere_and_quick(sample_video):
    found = oc.run(sample_video, [oc.LineSpan(0.2, 1.0), oc.LineSpan(1.2, 2.2)])
    assert found["status"] == "done"
    assert [ln["state"] for ln in found["lines"]] == [oc.OFF, oc.OFF]
    assert found["seconds"] < 10


def test_a_crash_leaves_every_line_unsure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad file")
    monkeypatch.setattr(oc, "detect", boom)
    found = oc.run("x.mp4", [oc.LineSpan(0, 1)])
    assert found["status"] == "failed" and found["lines"][0]["state"] == oc.UNSURE
