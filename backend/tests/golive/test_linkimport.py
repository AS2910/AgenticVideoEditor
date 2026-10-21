"""G1: the link importers (unit). No network: every download runs on an
httpx.MockTransport."""
from pathlib import Path

import httpx
import pytest

from app import linkimport as li

MP4_HEAD = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


@pytest.mark.parametrize("url", [
    "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing",
    "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp",
    "https://drive.google.com/uc?id=1AbCdEfGhIjKlMnOp&export=download",
])
def test_drive_share_links_resolve_to_the_download_address(url):
    r = li.resolve(url)
    assert r.provider == "drive" and r.url.startswith("https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp")
    assert "confirm=t" in r.url


def test_dropbox_links_ask_for_the_file_itself():
    r = li.resolve("https://www.dropbox.com/scl/fi/abc123/ad%20cut.mp4?rlkey=xyz&dl=0")
    assert r.provider == "dropbox" and "dl=1" in r.url and "dl=0" not in r.url and "rlkey=xyz" in r.url
    assert r.filename == "ad cut.mp4"
    assert "dl=1" in li.resolve("https://www.dropbox.com/s/abc/ad.mp4").url


def test_youtube_is_behind_the_interface_but_off_with_a_sentence():
    with pytest.raises(li.ImportRefused, match="connect your Google account"):
        li.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(li.ImportRefused, match="connect your Google account"):
        li.resolve("https://youtu.be/dQw4w9WgXcQ")
    assert not li.importer_for("https://youtu.be/x").enabled


@pytest.mark.parametrize("url, words", [
    ("not a link", "Paste a share link"),
    ("ftp://drive.google.com/file/d/1AbCdEfGhIjKlMnOp", "Paste a share link"),
    ("https://example.com/ad.mp4", "cannot import from example.com"),
    ("https://drive.google.com/drive/folders/", "does not point at a file"),
    ("https://www.dropbox.com/home/ads", "does not point at a file"),
])
def test_links_that_cannot_work_are_refused_with_a_sentence(url, words):
    with pytest.raises(li.ImportRefused, match=words):
        li.resolve(url)


def test_sniffing_knows_videos_and_pages():
    assert li.sniff(MP4_HEAD) == "mp4"
    assert li.sniff(b"\x00\x00\x00\x14ftypqt  \x00\x00") == "mov"
    assert li.sniff(b"\x1a\x45\xdf\xa3\x01\x00webm") == "webm"
    assert li.sniff(b"RIFF\x00\x00\x00\x00AVI LIST") == "avi"
    assert li.sniff(b"<!DOCTYPE html><html>") is None and li.looks_like_a_page(b"  <!doctype html>")


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def resolved():
    return li.Resolved("dropbox", "Dropbox", "https://www.dropbox.com/s/abc/ad.mp4?dl=1", "ad.mp4")


def test_a_video_downloads_with_progress_and_its_own_name(tmp_path):
    body = MP4_HEAD + b"x" * 5000
    seen = []
    out = li.download(resolved(), tmp_path, client=client_for(lambda r: httpx.Response(
        200, content=body, headers={"content-type": "video/mp4", "content-disposition": "attachment; filename=\"Spring cut.mp4\""})),
        on_progress=lambda got, total: seen.append((got, total)))
    assert out.name == "Spring cut.mp4" and out.read_bytes() == body
    assert seen[-1] == (len(body), len(body))


@pytest.mark.parametrize("response, words", [
    (httpx.Response(200, content=b"<html>sign in</html>", headers={"content-type": "text/html"}), "opens a page on Dropbox"),
    (httpx.Response(200, content=b"<!doctype html><p>hi", headers={"content-type": "application/octet-stream"}), "opens a page"),
    (httpx.Response(200, content=b"PK\x03\x04 a zip", headers={"content-type": "application/octet-stream"}), "not a video Voltage can read"),
    (httpx.Response(403), "would not share that file"),
    (httpx.Response(404), "does not exist"),
    (httpx.Response(200, content=b"", headers={"content-type": "video/mp4"}), "empty file"),
])
def test_a_download_that_is_not_a_video_is_refused(tmp_path, response, words):
    with pytest.raises(li.ImportRefused, match=words):
        li.download(resolved(), tmp_path, client=client_for(lambda r: response))


def test_the_size_cap_holds_from_the_header_and_while_streaming(tmp_path):
    big = httpx.Response(200, content=b"", headers={"content-length": str(3 * 1024 ** 3), "content-type": "video/mp4"})
    with pytest.raises(li.ImportRefused, match="3.0 GB. The limit for a link is 2.0 GB"):
        li.download(resolved(), tmp_path, client=client_for(lambda r: big))

    def unsized(r):
        return httpx.Response(200, content=iter([MP4_HEAD, b"x" * 4096]), headers={"content-type": "video/mp4"})
    with pytest.raises(li.ImportRefused, match="larger than"):
        li.download(resolved(), tmp_path, client=client_for(unsized), cap=1024)
    assert li.MAX_LINK_BYTES == 2 * 1024 ** 3


def test_a_network_failure_says_where(tmp_path):
    def down(r):
        raise httpx.ConnectError("no route")
    with pytest.raises(li.ImportRefused, match="Could not reach Dropbox"):
        li.download(resolved(), tmp_path, client=client_for(down))
