"""Launch item 2: uploads are what their bytes say, within 2 GB and 10 minutes."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, jobs, repo
from app.media import ingest, sniff
from tests.api.test_endpoints import upload


def setup_function():
    repo.reset()
    jobs.reset()


@pytest.mark.parametrize("head,kind", [
    (b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00", "mp4"), (b"\x00\x00\x00\x14ftypqt  ", "mov"),
    (b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01webm", "webm"), (b"\x1a\x45\xdf\xa3\x01matroska", "mkv"),
    (b"RIFF\x00\x00\x00\x00AVI LIST", "avi"),
])
def test_video_containers_are_known_by_their_bytes(head, kind):
    assert sniff.video(head) == kind


@pytest.mark.parametrize("head", [b"\x89PNG\r\n\x1a\n", b"MZ\x90\x00", b"<html><script>", b"%PDF-1.7", b"\x00\x00\x00\x18ftypM4A "])
def test_anything_else_is_not_a_video(head):
    with pytest.raises(sniff.SniffError, match="Upload an MP4, MOV, WebM, MKV or AVI video"):
        sniff.video(head)


def test_audio_and_documents():
    assert sniff.audio(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav" and sniff.audio(b"ID3\x04") == "mp3"
    assert sniff.audio(b"OggS\x00") == "ogg" and sniff.audio(b"\x1a\x45\xdf\xa3webm") == "webm"
    with pytest.raises(sniff.SniffError):
        sniff.audio(b"\x89PNG\r\n")
    assert sniff.document(b"%PDF-1.4", "brief.pdf") == "pdf"
    assert sniff.document("Brief: 20% off. ₹".encode(), "brief.md") == "md"
    assert sniff.document(b"PK\x03\x04", "brief.docx") == "docx"
    for head, name in ((b"PK\x03\x04", "brief.zip"), (b"MZ\x90\x00\x03\x00", "brief.txt")):
        with pytest.raises(sniff.SniffError):
            sniff.document(head, name)


def test_a_file_named_mp4_that_is_not_a_video_is_refused_with_a_clear_reason(tmp_path):
    fake = tmp_path / "ad.mp4"
    fake.write_bytes(b"#!/bin/sh\necho pwned\n" * 10)
    resp = upload(TestClient(app), fake)
    assert resp.status_code == 415
    assert resp.json()["detail"] == "That file is not a video we can take. Upload an MP4, MOV, WebM, MKV or AVI video."
    assert repo.list("local") == []


def test_too_long_and_too_big_say_the_limits(sample_video, monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 1.0)
    resp = upload(TestClient(app), sample_video)
    assert resp.status_code == 422 and "up to 1 s for now; trim it and upload it again" in resp.json()["detail"]
    monkeypatch.setattr(ingest, "MAX_SOURCE_SECONDS", 600.0)
    monkeypatch.setattr(ingest, "MAX_SOURCE_BYTES", 1024)
    resp = upload(TestClient(app), sample_video)
    assert resp.status_code == 413 and "Videos can be up to" in resp.json()["detail"]


def test_the_launch_limits_are_ten_minutes_and_two_gigabytes():
    assert ingest.MAX_SOURCE_SECONDS == 600.0 and ingest.MAX_SOURCE_BYTES == 2048 << 20


def test_a_reference_file_must_be_a_document():
    client = TestClient(app)
    folder = client.post("/projects", json={"name": "P"}).json()["project_id"]
    bad = client.post(f"/projects/{folder}/files", files={"file": ("notes.txt", b"MZ\x90\x00\x03\x00\x00\x00", "text/plain")})
    assert bad.status_code == 415 and "Upload a text, Markdown" in bad.json()["detail"]
    good = client.post(f"/projects/{folder}/files", files={"file": ("notes.md", b"Say Bhaji Cam.", "text/markdown")})
    assert good.status_code == 201
