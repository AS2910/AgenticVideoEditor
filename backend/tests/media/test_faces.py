"""Where there is a mouth to move (Phase 17b). No model is loaded: the face
count and the frame reader are injected, except in the one test that uses the
real vendored detector on a real face when OpenCV is installed."""
import pytest

from app.media import faces
from app.media.faces import Stretch


def counter(faces_by_time):
    """A face count keyed on the time a frame was read at (the reader returns the time as the 'frame')."""
    return lambda t: next((n for (a, b), n in faces_by_time.items() if a <= t < b), 0)


def reader(path, at):
    return at


def test_a_span_is_split_at_the_cuts_inside_it():
    assert faces.shots_within(1.0, 4.0, [0.5, 2.0, 3.0, 4.0, 9.0]) == [(1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]
    assert faces.shots_within(1.0, 4.0, []) == [(1.0, 4.0)]


def test_samples_sit_inside_each_slice_and_are_bounded():
    times = faces.sample_times(10.0, 12.0)
    assert len(times) == 8 and all(10.0 < t < 12.0 for t in times)
    assert len(faces.sample_times(0.0, 60.0)) == faces.MAX_SAMPLES
    assert faces.sample_times(0.0, 0.1) and len(faces.sample_times(0.0, 0.1)) == 1


def test_only_a_shot_with_a_face_for_most_of_it_is_sent():
    # A phone close-up (no face), the shopkeeper, then a shot where a face appears only briefly.
    count = counter({(1.0, 2.0): 0, (2.0, 3.5): 1, (3.5, 4.0): 0})
    count_sparse = lambda t: 1 if 3.5 <= t < 3.6 else count(t)          # noqa: E731
    out = faces.stretches("v.mp4", 1.0, 4.0, [2.0, 3.5], count=count_sparse, read=reader)
    assert out == [Stretch(2.0, 3.5, 1)]


def test_more_than_one_face_is_reported_so_the_speaker_can_be_picked():
    out = faces.stretches("v.mp4", 0.0, 2.0, [], count=lambda t: 2, read=reader)
    assert out == [Stretch(0.0, 2.0, 2)] and out[0].faces == 2


def test_a_shot_too_short_for_the_vendor_is_left_alone():
    out = faces.stretches("v.mp4", 0.0, 1.0, [0.7], count=lambda t: 1, read=reader)
    assert [(s.start, s.end) for s in out] == [(0.0, 0.7)]               # 0.3 s after the cut is dropped


def test_an_unreadable_frame_counts_as_no_face():
    out = faces.stretches("v.mp4", 0.0, 2.0, [], count=lambda t: 1, read=lambda p, t: None)
    assert out == []


def test_without_a_face_finder_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(faces, "available", lambda: False)
    assert faces.stretches("v.mp4", 0.0, 2.0, []) == []


@pytest.mark.skipif(not faces.available(), reason="needs the `mouth` extra (OpenCV)")
def test_a_face_cut_by_the_frame_or_too_small_is_not_a_mouth_to_move():
    W, H = 1280, 720
    assert faces.usable_face(500, 100, 200, 260, W, H)              # whole, a good size
    assert not faces.usable_face(1100, 100, 200, 260, W, H)         # runs off the right edge
    assert not faces.usable_face(500, -20, 200, 260, W, H)          # runs off the top
    assert not faces.usable_face(500, 100, 40, 50, W, H)            # a speck: under 10% of the height


def test_the_real_detector_finds_the_face_in_a_real_frame():
    import cv2
    from pathlib import Path
    frame = cv2.imread(str(Path(__file__).parents[1] / "fixtures" / "face.jpg"))
    if frame is None:
        pytest.skip("no face fixture")
    assert faces._count_faces(frame) >= 1
