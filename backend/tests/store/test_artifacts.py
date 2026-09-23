from pathlib import Path

from app.store.artifacts import ArtifactStore

AUDIO = dict(kind="audio", container="wav", duration=0.9)


def test_put_bytes_writes_a_file_named_by_its_content_hash(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact = store.put_bytes("p1", b"hello", **AUDIO)

    on_disk = Path(artifact.path)
    assert on_disk.is_file()
    assert on_disk.read_bytes() == b"hello"
    assert on_disk.name == f"{artifact.sha256}.wav"
    assert artifact.kind == "audio"
    assert artifact.duration == 0.9


def test_identical_bytes_collapse_onto_one_file(tmp_path):
    store = ArtifactStore(tmp_path)
    a = store.put_bytes("p1", b"same", **AUDIO)
    b = store.put_bytes("p1", b"same", **AUDIO)

    assert a == b
    assert len(list((tmp_path / "p1").iterdir())) == 1


def test_different_bytes_get_different_addresses(tmp_path):
    store = ArtifactStore(tmp_path)
    a = store.put_bytes("p1", b"one", **AUDIO)
    b = store.put_bytes("p1", b"two", **AUDIO)

    assert a.sha256 != b.sha256
    assert len(list((tmp_path / "p1").iterdir())) == 2


def test_projects_are_namespaced(tmp_path):
    store = ArtifactStore(tmp_path)
    a = store.put_bytes("p1", b"same", **AUDIO)
    b = store.put_bytes("p2", b"same", **AUDIO)

    assert a.sha256 == b.sha256
    assert a.path != b.path
    assert Path(a.path).is_file() and Path(b.path).is_file()


def test_put_file_adopts_an_externally_produced_file(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    src = tmp_path / "produced.mp4"
    src.write_bytes(b"frames")

    artifact = store.put_file("p1", src, kind="video", container="mp4", duration=1.5)

    assert Path(artifact.path).read_bytes() == b"frames"
    assert artifact.kind == "video" and artifact.container == "mp4"
    assert src.is_file()  # the source is copied, not consumed


def test_exists_reports_whether_the_bytes_are_still_there(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact = store.put_bytes("p1", b"x", **AUDIO)
    assert store.exists(artifact) is True

    Path(artifact.path).unlink()
    assert store.exists(artifact) is False


def test_no_temp_files_are_left_behind(tmp_path):
    store = ArtifactStore(tmp_path)
    store.put_bytes("p1", b"x", **AUDIO)
    assert [p.name for p in (tmp_path / "p1").iterdir() if p.suffix == ".tmp"] == []
