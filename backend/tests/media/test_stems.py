"""Stem separation, with a fake separator: the model never loads here."""
import hashlib
import wave

from app.media import stems


def _wav(path, seed=b"a"):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(seed * 1600)
    return path


class Fake:
    def __init__(self):
        self.calls = 0

    def __call__(self, wav, out):
        self.calls += 1
        folder = out / stems.MODEL / wav.stem
        folder.mkdir(parents=True)
        (folder / "vocals.wav").write_bytes(b"v")
        (folder / "no_vocals.wav").write_bytes(b"n")


def test_separate_returns_both_stems(tmp_path):
    wav = _wav(tmp_path / "clip.wav")
    result = stems.separate(wav, tmp_path / "cache", run=Fake())
    assert result is not None
    assert result.vocals.read_bytes() == b"v"
    assert result.accompaniment.read_bytes() == b"n"
    assert hashlib.sha256(wav.read_bytes()).hexdigest() in str(result.vocals)


def test_a_second_render_hits_the_cache(tmp_path):
    wav, run = _wav(tmp_path / "clip.wav"), Fake()
    first = stems.separate(wav, tmp_path / "cache", run=run)
    second = stems.separate(wav, tmp_path / "cache", run=run)
    assert run.calls == 1 and first == second
    # Different audio is a different key.
    stems.separate(_wav(tmp_path / "other.wav", b"b"), tmp_path / "cache", run=run)
    assert run.calls == 2


def test_failures_are_none_not_exceptions(tmp_path):
    wav = _wav(tmp_path / "clip.wav")

    def boom(*_):
        raise RuntimeError("no model")

    assert stems.separate(wav, tmp_path / "c1", run=boom) is None
    assert stems.separate(wav, tmp_path / "c2", run=lambda *_: None) is None   # wrote nothing
    assert stems.separate(tmp_path / "missing.wav", tmp_path / "c3", run=Fake()) is None


def test_unavailable_demucs_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(stems, "available", lambda: False)
    assert stems.separate(_wav(tmp_path / "clip.wav"), tmp_path / "cache") is None


def test_two_asks_at_once_separate_once(tmp_path):
    """Run 5 item 8: the upload's background job and an export can ask together."""
    import threading
    import time
    wav = _wav(tmp_path / "clip.wav")

    class Slow(Fake):
        def __call__(self, wav, out):
            time.sleep(0.2)
            super().__call__(wav, out)
    run, got = Slow(), []
    threads = [threading.Thread(target=lambda: got.append(stems.separate(wav, tmp_path / "cache", run=run)))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert run.calls == 1 and len(got) == 3 and all(g is not None and g == got[0] for g in got)
