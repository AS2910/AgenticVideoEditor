"""LSE-D / LSE-C with a fake embedder: nothing here loads SyncNet."""
import numpy as np
import pytest

from app.continuity import lipsync_measure as lm
from app.continuity import measured
from app.continuity.lipsync_measure import LseScore
from app.media import ffmpeg

needs_cv2 = pytest.mark.skipif(not lm.available(), reason="needs the `mouth` extra")


def feats(n=60, dim=64, seed=1):
    return np.random.default_rng(seed).normal(size=(n, dim)) * 3


def test_perfect_sync_is_offset_zero_and_a_tiny_distance():
    v = feats()
    result = lm.score(lm.distances(v, v.copy()))
    assert result.offset_frames == 0
    assert result.distance == pytest.approx(0.0, abs=1e-3)
    assert result.confidence > 10


def test_a_shifted_audio_is_found_at_its_offset():
    v = feats()
    # audio[i + 3] = video[i]: the sound runs 3 pictures behind the lips
    result = lm.score(lm.distances(v, np.roll(v, 3, axis=0)))
    assert result.offset_frames == -3
    assert result.distance < 4          # a few rows fell off the end
    ahead = lm.score(lm.distances(v, np.roll(v, -5, axis=0)))
    assert ahead.offset_frames == 5


def test_lse_d_is_the_smallest_mean_and_lse_c_the_median_less_it():
    dists = np.full((4, 2 * lm.MAX_SHIFT + 1), 5.0)
    dists[:, lm.MAX_SHIFT + 2] = [1.0, 2.0, 3.0, 2.0]    # mean 2.0, at offset -2
    result = lm.score(dists)
    assert result == LseScore(distance=2.0, confidence=3.0, offset_frames=-2)


def test_unrelated_audio_reads_far_and_unsure():
    result = lm.score(lm.distances(feats(seed=1), feats(seed=2)))
    assert result.distance > 15
    assert result.confidence < 3


def test_distance_curve_covers_minus_fifteen_to_plus_fifteen():
    assert lm.distances(feats(10), feats(10)).shape == (10, 31)


@pytest.mark.parametrize("edited, original, expect", [
    (2.0, 5.0, 1.0),              # better than the original's own: full marks
    (5.0, 5.0, 1.0),
    (6.0, 5.0, 0.75),
    (9.0, 5.0, 0.0),              # +4.0 is the floor
    (14.0, 5.0, 0.0),
])
def test_lip_sync_score_falls_linearly_to_zero_at_four_over(edited, original, expect):
    got = lm.lip_sync_score(LseScore(edited, 5.0, 0), LseScore(original, 5.0, 0))
    assert got == pytest.approx(expect)


def test_lip_sync_score_is_none_when_either_side_is_unmeasured():
    s = LseScore(5.0, 5.0, 0)
    assert lm.lip_sync_score(None, s) is None
    assert lm.lip_sync_score(s, None) is None
    assert lm.lip_sync_score(None, None) is None


def test_pass_within_is_the_roadmap_exit():
    assert lm.PASS_WITHIN == 1.0


def test_unavailable_gives_none(monkeypatch, tmp_path):
    monkeypatch.setenv("AVE_MOUTH_MEASURE", "0")
    assert lm.available() is False
    assert lm.lse(tmp_path / "x.mp4") is None


def test_a_model_that_cannot_load_gives_none(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "_model", None)
    monkeypatch.setattr(lm, "_failed", True)
    assert lm.lse(tmp_path / "x.mp4") is None


def test_mfcc_is_thirteen_coefficients_every_ten_ms():
    x = (0.3 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(np.float32)
    out = lm.mfcc(x)
    assert out.shape == (13, 99)
    assert np.isfinite(out).all()


def test_the_dct_is_the_orthonormal_type_two():
    x = np.random.default_rng(0).normal(size=26)
    for k in (0, 1, 7):
        scale = np.sqrt(1 / 26) if k == 0 else np.sqrt(2 / 26)
        direct = scale * sum(x[i] * np.cos(np.pi * (i + 0.5) * k / 26) for i in range(26))
        assert (x @ lm._dct(26, 13))[k] == pytest.approx(direct)


# --- tracking the main face -------------------------------------------------------

def box(x=100.0, y=80.0, s=40.0):
    return (x, y, s)


def test_a_steady_face_is_one_run():
    runs = lm.track([box()] * 30)
    assert [(first, len(bs)) for first, bs in runs] == [(0, 30)]


def test_short_gaps_are_bridged_and_long_ones_split_the_run():
    bridged = lm.track([box()] * 10 + [None] * lm.MAX_GAP + [box()] * 10)
    assert [(f, len(b)) for f, b in bridged] == [(0, 10 + lm.MAX_GAP + 10)]
    split = lm.track([box()] * 20 + [None] * (lm.MAX_GAP + 1) + [box()] * 20)
    assert [(f, len(b)) for f, b in split] == [(0, 20), (20 + lm.MAX_GAP + 1, 20)]


def test_a_run_under_the_minimum_is_dropped():
    short = int(lm.MIN_SECONDS * lm.FPS) - 1
    assert lm.track([box()] * short) == []
    assert lm.track([None] * 50) == []


def test_a_jump_to_another_place_is_a_cut_and_starts_a_new_run():
    runs = lm.track([box(x=100)] * 20 + [box(x=400)] * 20)
    assert [(f, len(b)) for f, b in runs] == [(0, 20), (20, 20)]


def test_a_single_wild_detection_does_not_shake_the_crop():
    boxes = [box()] * 30
    boxes[15] = box(x=104, s=70)
    smooth = lm.track(boxes)[0][1]
    assert smooth[15] == box()


@needs_cv2
def test_a_crop_is_224_square_even_at_the_edge_of_the_picture():
    frame = np.full((120, 160, 3), 200, np.uint8)
    for b in (box(80, 60, 30), box(5, 5, 30), box(155, 118, 60)):
        out = lm.crop(frame, b)
        assert out.shape == (224, 224, 3) and out.dtype == np.uint8


@needs_cv2
def test_the_crop_keeps_the_face_in_the_top_and_leaves_room_below_the_chin():
    frame = np.zeros((300, 300, 3), np.uint8)
    frame[110:150, 130:170] = 255                      # the "face", 40 px, centred (150, 130)
    out = lm.crop(frame, (150.0, 130.0, 20.0))
    rows = np.where(out[:, :, 0].mean(axis=1) > 128)[0]
    assert rows.min() <= 2 and 224 * 0.65 < rows.max() < 224 * 0.8     # face box fills the top ~70%


# --- lse(): runs of face, and the audio that goes with each ---------------------

def wav(tmp_path, name, seconds):
    t = np.arange(int(seconds * 16000)) / 16000
    path = tmp_path / name
    measured._write_wav(path, (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 16000)
    return path


def fake_runs(monkeypatch, *spans):
    """face_runs() stand-in: (first picture, picture count) -> blank crops."""
    monkeypatch.setattr(lm, "face_runs", lambda v: [
        (first, np.zeros((n, lm.FACE_SIZE, lm.FACE_SIZE, 3), np.uint8)) for first, n in spans
    ])


@pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
def test_lse_pairs_each_run_with_its_own_slice_of_the_audio(monkeypatch, tmp_path):
    fake_runs(monkeypatch, (0, 50), (75, 50))
    audio = wav(tmp_path, "a.wav", 5.0)
    seen = []

    def embed(frames, mfcc):
        seen.append((len(frames), mfcc.shape[1]))
        n = len(frames) - lm.WINDOW + 1
        v = feats(n, seed=len(seen))
        return v, v

    result = lm.lse(tmp_path / "v.mp4", audio, embed=embed)
    assert result is not None and result.offset_frames == 0 and result.distance < 1e-3
    assert [n for n, _ in seen] == [50, 50]
    assert all(frames * 4 - 5 <= m <= frames * 4 + 5 for frames, m in seen)   # 100 MFCC frames a second


@pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
def test_lse_is_none_without_a_face_or_with_a_failing_model(monkeypatch, tmp_path):
    audio = wav(tmp_path, "a.wav", 3.0)
    ok = lambda frames, mfcc: (feats(10), feats(10))         
    fake_runs(monkeypatch)
    assert lm.lse(tmp_path / "v.mp4", audio, embed=ok) is None

    fake_runs(monkeypatch, (0, 50))

    def boom(frames, mfcc):
        raise RuntimeError("out of memory")

    assert lm.lse(tmp_path / "v.mp4", audio, embed=boom) is None


@needs_cv2
@pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")
def test_a_video_with_no_face_gives_none(tmp_path):
    video = tmp_path / "blank.mp4"
    ffmpeg.generate_solid_video(video, 2.0)
    assert lm.lse(video, embed=lambda f, m: (feats(10), feats(10))) is None
