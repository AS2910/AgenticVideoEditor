"""Launch item 5: a share token is unguessable (64 random bits of id, 144
bits of HMAC), and one link's token reaches only its own files: not another
link's, not another project's, not after it is turned off."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.media import ffmpeg
from app.store import shares
from tests.factories import export_now  # noqa: E402


def test_a_share_token_is_long_and_random():
    import inspect
    assert 'secrets.token_hex(8)' in inspect.getsource(shares.create_in)          # 64 random bits of id
    sig = shares._sign("k" * 32, "sh" + "0" * 16, "project", "f1", "viewer", "2026-12-01T00:00:00.000Z")
    assert len(sig) == 24                                                          # 144 bits of HMAC-SHA256


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
def test_one_link_reaches_only_its_own_files(sample_video):
    from tests.api.test_folders import upload_into
    main.repo.reset()
    main.jobs.reset()
    client = TestClient(main.app)
    client.post("/projects", json={"name": "A"})
    client.post("/projects", json={"name": "B"})
    upload_into(client, sample_video, "f1", name="a.mp4")
    upload_into(client, sample_video, "f2", name="b.mp4")
    for vid in ("p1", "p2"):
        assert export_now(client, f"/videos/{vid}/export", json={"purpose": "export"}).status_code == 200
    link_a = client.post("/projects/f1/shares", json={"scope": "project"}).json()
    link_b = client.post("/projects/f2/shares", json={"scope": "project"}).json()
    token_a, token_b = (link["url"].split("/#s/")[1] for link in (link_a, link_b))
    file_b = client.get(f"/share/{token_b}").json()["files"][0]["file_id"]
    assert client.get(f"/share/{token_b}/files/{file_b}").status_code == 200
    assert client.get(f"/share/{token_a}/files/{file_b}").status_code == 404          # B's file through A's link
    # A's id with B's signature, and the reverse, are forgeries.
    a_id, a_sig = token_a.split(".")
    b_id, b_sig = token_b.split(".")
    assert client.get(f"/share/{a_id}.{b_sig}").status_code == 404
    assert client.get(f"/share/{b_id}.{a_sig}/files/{file_b}").status_code == 404
    # Turned off: refused at once, files and zip too.
    client.delete(f"/projects/f2/shares/{link_b['share_id']}")
    for path in (f"/share/{token_b}", f"/share/{token_b}/files/{file_b}", f"/share/{token_b}/zip"):
        assert client.get(path).status_code == 410, path
    assert len(token_a) > 40
