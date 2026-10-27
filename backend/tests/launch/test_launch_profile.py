"""Launch item 10: AVE_LAUNCH_PROFILE=public turns the launch's features on
for everyone; Phases C, D and A2 stay off and an admin can turn them on
for one person. Run 5 item 9: phase B (B1 to B3, `projects.batch`) is on in
the profile while `launch.batch_public` is on, which it is by default."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, flags
from app.config import load_settings
from app.flags import ALL, BATCH_PUBLIC, KNOWN, OFF_BY_DEFAULT, PROFILES, FlagStore, main as flags_main
from app.store.db import Database

PUBLIC_ON = {"projects.consistency", "golive.g1", "golive.g2", "golive.g3", "golive.g4", "golive.g6", "golive.g7", "golive.g8"}
# What launch.batch_public (on by default) adds to the profile.
BATCH_ON = {"launch.batch_public", "projects.batch"}
PUBLIC_OFF = {"projects.review", "projects.reuse", "projects.check", "golive.g5", "voices.cloning", "voices.cloning_verified"}


def test_the_public_profile_turns_on_exactly_the_launch_features():
    store = FlagStore(Database(), ("local",), "public")
    stranger = "acct:abc"
    on = set(store.enabled_for(stranger))
    assert on == PUBLIC_ON | BATCH_ON and PROFILES["public"] == PUBLIC_ON
    assert not (on & PUBLIC_OFF)
    assert set(store.enabled_for("local")) >= set(KNOWN) - {f for f in KNOWN if f.startswith("launch.")} - OFF_BY_DEFAULT


def test_without_a_profile_strangers_get_nothing():
    # The switch itself is on, but it only widens a launch profile.
    assert FlagStore(Database(), ("local",)).enabled_for("acct:abc") == [BATCH_PUBLIC]


def test_batch_public_brings_phase_b_and_turns_off_in_one_place():
    store = FlagStore(Database(), ("local",), "public")
    stranger = "acct:abc"
    assert store.enabled(BATCH_PUBLIC, stranger) and store.enabled("projects.batch", stranger)
    # B1 to B3 need only projects.batch: A2 and phase C stay off.
    assert not store.enabled("projects.check", stranger) and not store.enabled("projects.review", stranger)
    sources = {f["flag"]: f["source"] for f in store.explain(stranger)}
    assert sources[BATCH_PUBLIC] == "default" and sources["projects.batch"] == "profile"
    store.set(BATCH_PUBLIC, ALL, False)                             # off for everyone
    assert not store.enabled("projects.batch", stranger)
    assert set(store.enabled_for(stranger)) == PUBLIC_ON
    store.set("projects.batch", stranger, True)                     # a person's own row still wins
    assert store.enabled("projects.batch", stranger) and not store.enabled("projects.batch", "acct:other")
    store.clear(BATCH_PUBLIC, ALL)
    assert store.enabled("projects.batch", "acct:other")


def test_an_admin_turns_a_phase_on_for_one_person(monkeypatch):
    monkeypatch.setattr(main, "flags", FlagStore(main.database, ("local",), "public"))
    client = TestClient(app)
    H = {"X-Requested-With": "voltage"}
    seen = client.get("/admin/flags", params={"owner": "acct:abc"}).json()
    row = {f["flag"]: f for f in seen["flags"]}
    assert row["projects.review"] == {"flag": "projects.review", "on": False, "source": "off"}
    assert row["golive.g3"]["source"] == "profile"
    after = client.put("/admin/flags", json={"owner": "acct:abc", "flag": "projects.review", "enabled": True}, headers=H).json()
    assert {f["flag"]: f for f in after["flags"]}["projects.review"] == {"flag": "projects.review", "on": True, "source": "owner"}
    assert main.flags.enabled("projects.review", "acct:abc") and not main.flags.enabled("projects.review", "acct:other")
    client.put("/admin/flags", json={"owner": "acct:abc", "flag": "projects.review", "enabled": None}, headers=H)
    assert not main.flags.enabled("projects.review", "acct:abc")
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
    assert "on   golive.g3" in out and "on   projects.batch (while launch.batch_public is on)" in out
    assert "on   launch.batch_public" in out and "off  projects.review" in out


def test_the_landing_page_offers_language_versions_while_batch_public_is_on(monkeypatch):
    store = FlagStore(main.database, ("local",), "public")
    monkeypatch.setattr(main, "flags", store)
    client = TestClient(app)
    try:
        assert client.get("/pricing").json()["languages"] is True
        store.set(BATCH_PUBLIC, ALL, False)
        assert client.get("/pricing").json()["languages"] is False
    finally:
        store.clear(BATCH_PUBLIC, ALL)
