"""Run 5, item 10: the LipSyncProvider seam. Only the changed span plus its
handles is sent, and the result is laid back frame for frame. The fake does
the round trip; the vendor and self-hosted stubs stay off without keys and are
checked on mocked HTTP only."""
import subprocess
from pathlib import Path

import httpx
import pytest

from app.lipsync import provider as lp
from app.lipsync.fake import FakeLipSyncProvider
from app.lipsync.selfhosted import SelfHostedLipSyncProvider
from app.lipsync.vendor import SyncSoLipSyncProvider
from app.media import ffmpeg

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
FPS = 25


def test_the_window_adds_half_a_second_each_side():
    w = lp.window(3.0, 5.0, 12.0)
    assert (w.send_start, w.send_end, w.lead, w.seconds) == (2.5, 5.5, 0.5, 3.0)


def test_the_window_stops_at_the_clip_edges_and_at_cuts():
    assert lp.window(0.2, 1.0, 1.3) == lp.Window(0.2, 1.0, 0.0, 1.3)
    w = lp.window(3.0, 5.0, 12.0, cuts=[2.8, 5.2, 9.0])
    assert (w.send_start, w.send_end) == (2.8, 5.2)


def test_an_empty_span_is_refused():
    with pytest.raises(ValueError):
        lp.window(2.0, 2.0, 5.0)


def test_both_real_providers_are_off_without_keys_and_nothing_is_selected():
    status = lp.status()
    assert status["selected"] == "off"
    assert {p["name"]: p["available"] for p in status["providers"]} == {"fake": True, "sync_so": False, "selfhosted": False}


def test_a_key_alone_never_switches_the_vendor_on(monkeypatch):
    monkeypatch.setenv("SYNC_API_KEY", "sk-test")
    assert not SyncSoLipSyncProvider.from_env().available()
    monkeypatch.setenv("AVE_LIPSYNC_PROVIDER", "sync_so")
    on = SyncSoLipSyncProvider.from_env()
    assert on.available() and on.usd_for(2.0) == 0.12
    monkeypatch.setenv("SYNC_API_KEY", "")
    assert not SyncSoLipSyncProvider.from_env().available()


def test_selfhosted_needs_both_the_switch_and_the_endpoint(monkeypatch):
    monkeypatch.setenv("LIPSYNC_SELFHOSTED_URL", "http://gpu.local:8000")
    assert not SelfHostedLipSyncProvider.from_env().available()
    monkeypatch.setenv("AVE_LIPSYNC_PROVIDER", "selfhosted")
    assert SelfHostedLipSyncProvider.from_env().available()
    assert lp.status()["selected"] == "selfhosted"


def test_an_off_provider_refuses_before_anything_is_cut(tmp_path):
    with pytest.raises(lp.LipSyncUnavailable):
        lp.replace_span(SyncSoLipSyncProvider(None), tmp_path / "x.mp4", tmp_path / "t.wav", 1, 2, 5, tmp_path)


def test_a_span_shorter_than_the_vendor_takes_is_refused(tmp_path):
    with pytest.raises(lp.LipSyncUnavailable, match="too short"):
        lp.replace_span(FakeLipSyncProvider(), tmp_path / "x.mp4", tmp_path / "t.wav", 1.0, 1.2, 5, tmp_path)


def _clip(path: Path, seconds: float) -> Path:
    subprocess.run([ffmpeg.FFMPEG, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=s=320x240:r={FPS}:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def _frames(path: Path) -> int:
    out = subprocess.run([ffmpeg.FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def _bottom_green(path: Path, at: float) -> bool:
    raw = subprocess.run([ffmpeg.FFMPEG, "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "crop=iw:4:0:ih-4,scale=1:1,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    r, g, b = raw[0], raw[1], raw[2]
    return g > 180 and r < 160 and b < 100


@needs_ffmpeg
def test_only_the_span_and_its_handles_go_out_and_come_back_frame_for_frame(tmp_path):
    source = _clip(tmp_path / "source.mp4", 6.0)
    take, _ = ffmpeg.generate_tone(tmp_path / "take.wav", 1.5, 500)
    w, result, stitched = lp.replace_span(FakeLipSyncProvider(), source, take, 2.0, 3.5, 6.0, tmp_path / "work",
                                          stitched=tmp_path / "out.mp4")
    assert (w.send_start, w.send_end) == (1.5, 4.0)
    assert ffmpeg.duration_of(tmp_path / "work" / "window.mp4") == pytest.approx(2.5, abs=0.05)
    assert ffmpeg.duration_of(tmp_path / "work" / "window.wav") == pytest.approx(2.5, abs=0.05)
    assert result.provider == "fake" and result.usd == 0
    assert _frames(stitched) == _frames(source)
    # The fake marks the changed span only: not in the handles, not outside the window.
    assert _bottom_green(stitched, 2.7)
    assert not _bottom_green(stitched, 1.7)
    assert not _bottom_green(stitched, 1.0)
    assert not _bottom_green(stitched, 5.0)


@needs_ffmpeg
def test_the_selfhosted_stub_posts_the_window_and_writes_what_comes_back(tmp_path):
    source = _clip(tmp_path / "source.mp4", 3.0)
    take, _ = ffmpeg.generate_tone(tmp_path / "take.wav", 1.0, 500)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(200, content=(tmp_path / "work" / "window.mp4").read_bytes())

    stub = SelfHostedLipSyncProvider("http://gpu.local:8000/", "tok", 0.01, switched_on=True,
                                     http=httpx.Client(transport=httpx.MockTransport(handler)))
    w, result, _ = lp.replace_span(stub, source, take, 1.0, 2.0, 3.0, tmp_path / "work")
    assert seen["url"] == "http://gpu.local:8000/sync" and seen["auth"] == "Bearer tok"
    assert b'name="video"' in seen["body"] and b'name="audio"' in seen["body"]
    assert result.clip.exists() and result.usd == pytest.approx(0.02)


@needs_ffmpeg
def test_a_selfhosted_refusal_is_a_plain_unavailable(tmp_path):
    source = _clip(tmp_path / "source.mp4", 3.0)
    take, _ = ffmpeg.generate_tone(tmp_path / "take.wav", 1.0, 500)
    stub = SelfHostedLipSyncProvider("http://gpu.local", switched_on=True,
                                     http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(lp.LipSyncUnavailable, match="refused the clip"):
        lp.replace_span(stub, source, take, 1.0, 2.0, 3.0, tmp_path / "work")


@needs_ffmpeg
def test_the_vendor_stub_hands_the_window_to_the_sync_so_client(tmp_path):
    source = _clip(tmp_path / "source.mp4", 3.0)
    take, _ = ffmpeg.generate_tone(tmp_path / "take.wav", 1.0, 500)

    class Client:
        def move_mouth(self, video, audio, dest, model):
            self.sent = (Path(video).name, Path(audio).name, model)
            dest.write_bytes(Path(video).read_bytes())
            return dest, {"outputDuration": 2.0}

    client = Client()
    stub = SyncSoLipSyncProvider("sk-test", switched_on=True, client=client)
    _, result, _ = lp.replace_span(stub, source, take, 1.0, 2.0, 3.0, tmp_path / "work")
    assert client.sent == ("window.mp4", "window.wav", "lipsync-2")
    assert result.usd == pytest.approx(0.12)
