"""Launch item 5: names and keys from outside never leave their folder.

- an upload's filename (`..`, `..\\..\\x.mp4`, `/etc/x`) is made a bare name;
- an email address with slashes cannot become an owner id (an owner id is a
  folder name in the artifact store);
- the artifact store refuses keys with `.`/`..` parts or backslashes;
- every zip Voltage builds has bare, unique entry names (no zip-slip when
  the person unzips it, on Windows too);
- a .docx whose text XML unpacks to a zip bomb is not read."""
from __future__ import annotations

import io
import zipfile

import pytest

import app.api.main as main
from app.filenames import safe_filename, unique_names
from app.store import members
from app.store.artifacts import ArtifactStore


@pytest.mark.parametrize("raw, want", [
    ("..", "file"), (".", "file"), ("", "file"), (None, "file"),
    ("../../etc/passwd", "passwd"), ("..\\..\\evil.mp4", "evil.mp4"), ("/abs/path/x.mp4", "x.mp4"),
    ("C:\\Users\\a\\x.mp4", "x.mp4"), (".hidden.mp4", "hidden.mp4"), ("a\x00b\x1f.mp4", "ab.mp4"),
    ('we:ird<na>me?.mp4', "we-ird-na-me-.mp4"), ("Spring cut.mp4", "Spring cut.mp4"),
    ("x\u202egnp.mp4", "xgnp.mp4"),            # right-to-left override (a name that lies about its type)
])
def test_a_name_from_outside_is_a_bare_safe_name(raw, want):
    assert safe_filename(raw) == want


def test_a_long_name_keeps_its_type():
    got = safe_filename("a" * 400 + ".mp4")
    assert len(got) == 200 and got.endswith(".mp4")


def test_zip_names_are_unique_and_bare():
    assert unique_names(["../a.mp4", "a.mp4", "A.mp4", "..\\a.mp4", ".."], "video.mp4") == \
        ["a.mp4", "a-2.mp4", "A-3.mp4", "a-4.mp4", "video.mp4"]


@pytest.mark.parametrize("email", ["a/../../../../tmp/x@evil.com", "a\\b@evil.com", "x@evil.com/../../etc",
                                   "\"quoted\"@evil.com", "a..b@evil.com", ".a@evil.com", "a@-evil.com", "a@evil",
                                   "a@evil..com", "a\x00@evil.com"])
def test_an_address_that_could_name_a_path_is_refused(email):
    with pytest.raises(members.MemberError):
        members.clean_email(email)


@pytest.mark.parametrize("email", ["ann@example.com", "a.b+tag@mail.example.co.uk", "o'neil@example.ie", "x_y-z@sub-domain.example.com"])
def test_real_addresses_still_pass(email):
    assert members.clean_email(email.upper()) == email.lower()


def test_the_store_refuses_keys_that_climb_out(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    for key in ("..", ".", "", "a/../../x", "user-email:a/../../../tmp/x@evil.com", "a\\..\\b", "/abs", "a//b"):
        with pytest.raises(ValueError):
            store.put_bytes(key, b"x", kind="audio", container="wav", duration=0.0)
        assert store.find(key, "0" * 64) is None
    with pytest.raises(ValueError):
        store.put_bytes("p1", b"x", kind="audio", container="../x", duration=0.0)
    made = store.put_bytes("projects/f1/words", b"x", kind="audio", container="wav", duration=0.0)   # a real nested key
    assert store.find("projects/f1/words", made.sha256) is not None
    assert not (tmp_path / "tmp").exists()


def _zip_names(files):
    data = b"".join(main._zip_stream(files))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.namelist()


def test_a_zip_of_files_with_hostile_names_unpacks_in_place(tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"video")
    files = [{"name": n, "path": src} for n in ("..\\..\\Startup\\evil-voltage.mp4", "../../.bashrc", "/etc/cron.d/x.mp4",
                                                 "ok.mp4", "ok.mp4")]
    names = _zip_names(files)
    assert names == ["evil-voltage.mp4", "bashrc", "x.mp4", "ok.mp4", "ok-2.mp4"]
    assert not any("/" in n or "\\" in n or n.startswith(".") for n in names)


def test_an_upload_named_dot_dot_lands_as_a_plain_name(sample_video):
    from fastapi.testclient import TestClient
    main.repo.reset()
    main.jobs.reset()
    client = TestClient(main.app)
    with open(sample_video, "rb") as handle:
        made = client.post("/videos", files={"file": ("..\\..\\evil.mp4", handle, "video/mp4")}, data={"consent": "true"})
    assert made.status_code == 200, made.text
    assert made.json()["filename"] == "evil.mp4"
    with open(sample_video, "rb") as handle:
        dots = client.post("/videos", files={"file": ("..", handle, "video/mp4")}, data={"consent": "true"})
    assert dots.status_code == 200, dots.text       # before: a 500 (the file was spooled onto the temp folder itself)
    assert dots.json()["filename"] == "upload.mp4"


def _docx(xml_size: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"<w:p>" + b" " * xml_size + b"</w:p>")
    return buf.getvalue()


def test_a_docx_zip_bomb_is_not_unpacked(monkeypatch):
    monkeypatch.setattr(main, "MAX_DOCX_XML", 1024)
    small = main._extract_text("brief.docx", _docx(10))
    assert small.strip() == ""                         # read: only markup and spaces
    bomb = _docx(50 * 1024)                            # 50 KB of spaces squeezes to a few hundred bytes
    assert len(bomb) < 2048
    assert main._extract_text("bomb.docx", bomb) == ""


def test_a_docx_still_gives_its_words():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:p><w:t>Spring sale</w:t></w:p><w:p><w:t>ends Friday</w:t></w:p>")
    assert main._extract_text("brief.docx", buf.getvalue()).split() == ["Spring", "sale", "ends", "Friday"]


@pytest.mark.parametrize("name, body", [
    ("page.html", b"<html><script>fetch('/api/account',{method:'DELETE'})</script>"),
    ("pic.svg", b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"),
    ("fake.pdf", b"<html><script>alert(1)</script>"),
])
def test_a_reference_file_never_runs_as_a_page(name, body):
    """Any UTF-8 text is a valid reference file; served by its name's type, an
    .html or .svg one would have run as a page on Voltage's own address."""
    from fastapi.testclient import TestClient
    main.repo.reset()
    client = TestClient(main.app)
    folder = client.post("/projects", json={"name": "Refs"}).json()["project_id"]
    made = client.post(f"/projects/{folder}/files", files={"file": (name, body, "text/html")})
    assert made.status_code == 201, made.text
    sha = made.json()["sha256"]
    got = client.get(f"/projects/{folder}/files/{sha}", params={"mt": main.mint_media_token("local")["token"]})
    assert got.status_code == 200 and got.content == body
    kind = got.headers["content-type"]
    assert "html" not in kind and "svg" not in kind and "pdf" not in kind, kind
    assert "sandbox" in got.headers["content-security-policy"]
    assert got.headers["x-content-type-options"] == "nosniff"


def test_a_real_pdf_and_text_still_open_in_place():
    from fastapi.testclient import TestClient
    main.repo.reset()
    client = TestClient(main.app)
    folder = client.post("/projects", json={"name": "Refs"}).json()["project_id"]
    mt = {"mt": main.mint_media_token("local")["token"]}
    pdf = client.post(f"/projects/{folder}/files", files={"file": ("brief.pdf", b"%PDF-1.4 x", "application/pdf")}).json()
    got = client.get(f"/projects/{folder}/files/{pdf['sha256']}", params=mt)
    assert got.headers["content-type"] == "application/pdf" and got.headers["content-disposition"].startswith("inline")
    notes = client.post(f"/projects/{folder}/files", files={"file": ("notes.md", b"# Hi", "text/markdown")}).json()
    got = client.get(f"/projects/{folder}/files/{notes['sha256']}", params=mt)
    assert got.headers["content-type"].startswith("text/plain") and notes["kind"] == "md"
