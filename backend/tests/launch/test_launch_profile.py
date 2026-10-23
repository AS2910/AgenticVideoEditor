"""Launch item 10: AVE_LAUNCH_PROFILE=public turns the launch's features on
for everyone; Phases B, C, D and A2 stay off and an admin can turn them on
for one person."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, flags
from app.config import load_settings
from app.flags import KNOWN, PROFILES, FlagStore, main as flags_main
from app.store.db import Database

PUBLIC_ON = {"projects.consistency", "golive.g1", "golive.g2", "golive.g3", "golive.g4", "golive.g6", "golive.g7", "golive.g8"}
PUBLIC_OFF = {"projects.batch", "projects.review", "projects.reuse", "projects.check", "golive.g5", "voices.cloning"}


def test_the_public_profile_turns_on_exactly_the_launch_features():
    store = FlagStore(Database(), ("local",), "public")
    stranger = "acct:abc"
    on = set(store.enabled_for(stranger))
    assert on == PUBLIC_ON and PROFILES["public"] == PUBLIC_ON
    assert not (on & PUBLIC_OFF)
    assert set(store.enabled_for("local")) >= set(KNOWN) - {f for f in KNOWN if f.startswith("launch.")}


def test_without_a_profile_strangers_get_nothing():
    assert FlagStore(Database(), ("local",)).enabled_for("acct:abc") == []


def test_an_admin_turns_a_phase_on_for_one_person(monkeypatch):
    monkeypatch.setattr(main, "flags", FlagStore(main.database, ("local",), "public"))
    client = TestClient(app)
    H = {"X-Requested-With": "voltage"}
    seen = client.get("/admin/flags", params={"owner": "acct:abc"}).json()
    row = {f["flag"]: f for f in seen["flags"]}
    assert row["projects.batch"] == {"flag": "projects.batch", "on": False, "source": "off"}
    assert row["golive.g3"]["source"] == "profile"
    after = client.put("/admin/flags", json={"owner": "acct:abc", "flag": "projects.batch", "enabled": True}, headers=H).json()
    assert {f["flag"]: f for f in after["flags"]}["projects.batch"] == {"flag": "projects.batch", "on": True, "source": "owner"}
    assert main.flags.enabled("projects.batch", "acct:abc") and not main.flags.enabled("projects.batch", "acct:other")
    client.put("/admin/flags", json={"owner": "acct:abc", "flag": "projects.batch", "enabled": None}, headers=H)
    assert not main.flags.enabled("projects.batch", "acct:abc")
    assert client.put("/admin/flags", json={"owner": "acct:abc", "flag": "made.up", "enabled": True}, headers=H).status_code == 422


def test_the_project_check_needs_its_own_flag(monkeypatch):
    client = TestClient(app)
    folder = client.post("/projects", json={"name": "P"}).json()["project_id"]
    assert client.get(f"/projects/{folder}/check").status_code == 200
    flags.set("projects.check", "local", False)
    try:
        assert client.get(f"/projects/{folder}/check").status_code == 404
        assert client.get(f"/projects/{folder}/rules").status_code == 200       # A3 stays
    finally:
        flags.clear("projects.check", "local")


def test_the_profile_is_read_from_the_environment(monkeypatch, capsys):
    monkeypatch.setenv("AVE_LAUNCH_PROFILE", "public")
    assert load_settings().launch_profile == "public"
    monkeypatch.setenv("AVE_LAUNCH_PROFILE", "beta")
    with pytest.raises(ValueError):
        load_settings()
    flags_main(["profile"])
    out = capsys.readouterr().out
    assert "on   golive.g3" in out and "off  projects.batch" in out
