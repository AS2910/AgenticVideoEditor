"""B3: a delivered file from a render, with real ffmpeg on a tiny generated
clip: the platform's frame (padded, never cropped), the loudness target
within 1 LU as ffmpeg's own meter reads the file, the codec, and captions
burned into the picture at their times."""
import subprocess

import numpy as np
import pytest

from app.media import ffmpeg, loudness
from app.render import captions, deliver

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


def clip(tmp_path, size="320x180", seconds=4.0, name="src.mp4", volume=0.3):
    """Grey picture with a speech-like tone (bursts and pauses), stereo."""
    dest = tmp_path / name
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x808080:s={size}:r=25",
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000,volume='{volume}*gt(sin(2*PI*3*t),-0.2)':eval=frame",
        "-t", f"{seconds}", "-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dest),
    ])
    return dest


def frame_at(path, t, size):
    w, h = size
    raw, _ = ffmpeg.run_capture(["-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                                 "-pix_fmt", "gray", "-"], text=False)
    return np.frombuffer(raw, dtype=np.uint8)[: w * h].reshape(h, w)


@pytest.mark.parametrize("target", [-14.0, -16.0, -24.0])
def test_loudness_lands_within_one_lu_of_the_target(tmp_path, target):
    src = clip(tmp_path)
    report = deliver.deliver(src, tmp_path / "out.mp4", platform="youtube", loudness_lufs=target)
    measured = deliver.measure(tmp_path / "out.mp4")
    assert abs(measured["lufs"] - target) <= 1.0, measured
    assert abs(report["loudness_lufs"] - target) <= 1.0
    assert measured["true_peak_db"] <= report["true_peak_ceiling"] + 0.5
    # The mix's own meter agrees with ffmpeg's on the file as written.
    from app.render.compose import decode
    assert abs(loudness.loudness(decode(tmp_path / "out.mp4", channels=2).astype(np.float64)) - target) <= 1.0


@pytest.mark.parametrize("platform, size, framing", [
    ("youtube", (1920, 1080), "Fills the frame."),
    ("reels", (1080, 1920), "Letterboxed: black bars of 656 px above and below, nothing cropped."),
    ("feed", (1080, 1080), "Letterboxed: black bars of 236 px above and below, nothing cropped."),
])
def test_a_wide_clip_is_padded_into_each_platform_frame(tmp_path, platform, size, framing):
    src = clip(tmp_path, seconds=1.5)
    out = tmp_path / f"{platform}.mp4"
    report = deliver.deliver(src, out, platform=platform)
    video = [s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video"][0]
    assert (video["width"], video["height"]) == size and video["codec_name"] == "h264"
    assert report["framing"] == framing
    picture = frame_at(out, 0.5, size)
    w, h = report["picture"]
    top = (size[1] - h) // 2
    assert picture[top + h // 2, size[0] // 2] > 100                     # the grey shot, whole
    if top > 4:
        assert picture[top // 2, size[0] // 2] < 20                      # black bars, not cropped picture


def test_a_tall_clip_is_pillarboxed_for_youtube(tmp_path):
    src = clip(tmp_path, size="180x320", seconds=1.0)
    report = deliver.deliver(src, tmp_path / "out.mp4", platform="youtube")
    assert report["framing"].startswith("Pillarboxed") and report["picture"] == [608, 1080]


def test_fit_never_crops():
    assert deliver.fit(1920, 1080, (1080, 1920)) == (1080, 608, "Letterboxed: black bars of 656 px above and below, nothing cropped.")
    assert deliver.fit(1080, 1080, (1080, 1080))[2] == "Fills the frame."
    w, h, _ = deliver.fit(1000, 3000, (1080, 1080))
    assert w <= 1080 and h <= 1080 and h == 1080


def test_hevc_when_this_ffmpeg_writes_it(tmp_path):
    if "hevc" not in deliver.codecs():
        pytest.skip("no libx265 here")
    out = tmp_path / "out.mp4"
    deliver.deliver(clip(tmp_path, seconds=1.0), out, platform="feed", codec="hevc")
    video = [s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video"][0]
    assert video["codec_name"] == "hevc" and video.get("codec_tag_string") == "hvc1"


def test_an_unknown_codec_or_platform_is_refused(tmp_path):
    with pytest.raises(deliver.DeliverError, match="cannot write"):
        deliver.deliver(clip(tmp_path, seconds=0.5), tmp_path / "o.mp4", platform="feed", codec="prores")
    with pytest.raises(deliver.DeliverError, match="Unknown platform"):
        deliver.deliver(clip(tmp_path, seconds=0.5), tmp_path / "o.mp4", platform="tiktok")


def test_captions_are_burned_in_at_their_times_only(tmp_path):
    if deliver.caption_renderer() is None:
        pytest.skip("no libass and no OpenCV here")
    src = clip(tmp_path, seconds=3.0)
    cues = captions.cues([captions.Passage("Get 20% off this Diwali", 1.0, 2.0)])
    plain = tmp_path / "plain.mp4"
    out = tmp_path / "captioned.mp4"
    deliver.deliver(src, plain, platform="reels")
    report = deliver.deliver(src, out, platform="reels", cues=cues)
    assert report["captions"] == 1 and report["captions_renderer"] in ("libass", "opencv")
    size = (1080, 1920)
    band = slice(1920 - 384 - 200, 1920 - 384)                           # just above Reels' bottom fifth
    during = frame_at(out, 1.5, size)[band].astype(int)
    before = frame_at(out, 0.5, size)[band].astype(int)
    after = frame_at(out, 2.6, size)[band].astype(int)
    clean = frame_at(plain, 1.5, size)[band].astype(int)
    assert (during > 200).sum() > 500                                    # white letters
    assert np.abs(before - clean).max() < 30 and np.abs(after - clean).max() < 30


def test_captions_follow_the_video_as_edited():
    pieces = [{"start": 0.0, "end": 2.0, "out_start": 0.0, "out_end": 2.0, "kind": "copy", "factor": None},
              {"start": 2.0, "end": 2.0, "out_start": 2.0, "out_end": 3.5, "kind": "hold", "factor": None},
              {"start": 2.0, "end": 4.0, "out_start": 3.5, "out_end": 6.5, "kind": "flex", "factor": 1.5}]
    made = captions.cues([
        captions.Passage("Hello there", 0.2, 1.8),
        captions.Passage("A line the picture makes room for", 2.0, 2.0, added=True),
        captions.Passage("Stretched words", 2.0, 4.0),
    ], pieces)
    assert [(c.start, c.end, c.text) for c in made] == [
        (0.2, 1.8, "Hello there"), (2.0, 3.5, "A line the picture makes room for"), (3.5, 6.5, "Stretched words")]
    long = captions.cues([captions.Passage("word " * 40, 0.0, 8.0)])
    assert len(long) > 1 and all(len(c.lines) <= 2 and all(len(x) <= 42 for x in c.lines) for c in long)
    assert long[0].start == 0.0 and abs(long[-1].end - 8.0) < 0.01
    assert captions.srt(made).startswith("1\n00:00:00,200 --> 00:00:01,800\nHello there\n\n2\n")
