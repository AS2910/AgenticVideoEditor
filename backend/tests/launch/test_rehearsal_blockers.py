"""Rehearsal item 1: the launch blockers fixed in code. Cloning waits for a
real liveness check (voices.cloning, off in the public profile)."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.main as main
from app.agent.tools import _clone_speaker
from app.api.main import CLONING_CLOSED, app, flags

H = {"X-Requested-With": "voltage"}


def test_cloning_is_off_for_the_public_and_says_why():
    flags.set("voices.cloning", "local", False)
    try:
        client = TestClient(app)
        got = client.post("/voices/mine", data={"name": "Me", "consent": "true"},
                          files={"file": ("me.wav", b"RIFF0000WAVEfmt ", "audio/wav")}, headers=H)
        assert got.status_code == 403 and got.json()["detail"] == CLONING_CLOSED
        got = client.post("/voices/mine/from-speaker", json={"video_id": "nope", "label": "A", "name": "Me", "consent": True}, headers=H)
        assert got.status_code == 404          # someone else's (or no) video is not found first, as before
    finally:
        flags.clear("voices.cloning", "local")
    assert flags.enabled("voices.cloning", "local")


def test_with_cloning_closed_a_line_keeps_a_hand_picked_voice_or_the_one_asked_for(monkeypatch):
    flags.set("voices.cloning", "local", False)
    resolved = []
    monkeypatch.setattr(main.clones, "resolve", lambda *a, **k: resolved.append(a))
    monkeypatch.setattr(main, "speaker_of", lambda transcript, selection: "A")
    record = SimpleNamespace(owner="local", source=None, transcript=None)
    try:
        monkeypatch.setattr(main, "_speakers", lambda pid: [{"label": "A", "name": "", "voice_id": ""}])
        choice = main._voice_for("p1", record, None, "stock-voice")
        assert choice.voice_id == "stock-voice" and "not open yet" in " ".join(choice.notes)
        monkeypatch.setattr(main, "_speakers", lambda pid: [{"label": "A", "name": "", "voice_id": "picked"}])
        assert main._voice_for("p1", record, None, "stock-voice").voice_id == "picked"
        assert resolved == []                  # the clone service is never asked
    finally:
        flags.clear("voices.cloning", "local")


def test_the_agent_is_told_cloning_is_closed_before_anything_changes():
    calls = []
    wb = SimpleNamespace(voice_for=lambda *a: calls.append(a), cloning_open=lambda owner: owner == "open")
    turn = SimpleNamespace(record=SimpleNamespace(owner="closed"))
    out = _clone_speaker(wb, turn, {"speaker": "A"})
    assert "not open" in out.text and calls == []


def test_a_second_api_process_on_the_same_database_refuses_to_start(monkeypatch):
    import os
    import pytest
    from app import lease as lease_mod
    from app.store.db import Database
    db = Database(":memory:")
    first = lease_mod.acquire(db, host="vm-a")
    # Another host while the first is fresh: refused, with the reason.
    with pytest.raises(lease_mod.LeaseHeld, match="Run one API process only"):
        lease_mod.acquire(db, host="vm-b")
    # ...after the lease goes stale (a crash elsewhere): taken over.
    later = lease_mod.acquire(db, host="vm-b", now=lease_mod._read(db)["seen"] + lease_mod.TTL + 1)
    assert lease_mod._read(db)["id"] == later.id
    # Same host: a live other pid holds it; a dead pid (a restarted container) is taken over.
    with db.tx() as c:
        lease_mod._write(c, {"id": "x", "host": "vm-a", "pid": os.getppid(), "seen": 0})
    with pytest.raises(lease_mod.LeaseHeld):
        lease_mod.acquire(db, host="vm-a")
    with db.tx() as c:
        lease_mod._write(c, {"id": "x", "host": "vm-a", "pid": 999999, "seen": 9e12})
    taken = lease_mod.acquire(db, host="vm-a")
    taken.release()
    assert lease_mod._read(db) is None
    first.release()                             # not the holder any more: leaves nothing behind
    monkeypatch.setenv("AVE_ALLOW_SECOND_API", "1")
    with db.tx() as c:
        lease_mod._write(c, {"id": "x", "host": "vm-z", "pid": 1, "seen": 9e12})
    lease_mod.acquire(db, host="vm-b")


def test_the_server_takes_the_lease_while_it_runs_and_gives_it_back():
    from app import lease as lease_mod
    with TestClient(app):
        assert lease_mod._read(main.database)["pid"] == __import__("os").getpid()
    assert lease_mod._read(main.database) is None


def test_the_api_leaves_digests_to_the_worker_when_it_sends_them(monkeypatch):
    started = []
    monkeypatch.setattr(main.review_digests, "start", lambda: started.append(1))
    monkeypatch.setenv("AVE_WORKER_DIGESTS", "1")
    with TestClient(app):
        pass
    assert started == []
    monkeypatch.setenv("AVE_WORKER_DIGESTS", "0")
    with TestClient(app):
        pass
    assert started == [1]
