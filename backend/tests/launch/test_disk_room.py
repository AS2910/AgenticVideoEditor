"""Rehearsal item 4: a nearly full disk refuses new uploads and renders with
one sentence (507) and opens again once space is freed."""
from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app import diskroom
from app.api.main import app

Usage = namedtuple("Usage", "total used free")
H = {"X-Requested-With": "voltage"}


def test_the_disk_check_reads_percent_and_free_space(monkeypatch, tmp_path):
    monkeypatch.setattr(diskroom.shutil, "disk_usage", lambda p: Usage(100 << 30, 90 << 30, 10 << 30))
    diskroom.check(tmp_path)                                         # 90%: fine
    monkeypatch.setattr(diskroom.shutil, "disk_usage", lambda p: Usage(100 << 30, 95 << 30, 5 << 30))
    with pytest.raises(diskroom.DiskFull):
        diskroom.check(tmp_path)
    monkeypatch.setenv("AVE_DISK_FULL_PCT", "99")
    diskroom.check(tmp_path)
    monkeypatch.setattr(diskroom.shutil, "disk_usage", lambda p: Usage(2000 << 30, 1999 << 30, 1 << 29))
    with pytest.raises(diskroom.DiskFull):                           # 99.97% and under 1 GB free
        diskroom.check(tmp_path)


def test_an_upload_on_a_full_disk_is_refused_with_a_sentence(monkeypatch, sample_video):
    monkeypatch.setattr(diskroom.shutil, "disk_usage", lambda p: Usage(100 << 30, 96 << 30, 4 << 30))
    client = TestClient(app)
    with open(sample_video, "rb") as f:
        got = client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "true"}, headers=H)
    assert got.status_code == 507 and got.json()["detail"] == diskroom.SHORT
    monkeypatch.setattr(diskroom.shutil, "disk_usage", lambda p: Usage(100 << 30, 50 << 30, 50 << 30))
    with open(sample_video, "rb") as f:
        assert client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "true"}, headers=H).status_code == 200


def test_no_space_left_anywhere_says_so(monkeypatch):
    @app.get("/__drill_enospc")
    def boom():
        raise OSError(28, "No space left on device")
    try:
        got = TestClient(app, raise_server_exceptions=False).get("/__drill_enospc")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__drill_enospc"]
    assert got.status_code == 507 and "short of storage" in got.json()["detail"]
