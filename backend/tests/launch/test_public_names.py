"""Rehearsal item 7: pages name people by their address, never an owner id, and a
workspace shown to someone other than its owner is named after that owner (every
workspace is made as "My workspace", so a member's picker showed two the same).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import app.api.main as main
from app.api.main import database, flags, jobs, repo
from app.flags import KNOWN
from app.notify import email as email_mod
from tests.launch.test_roles import ANN, ED, RAE, H, _client, _join


@pytest.fixture(scope="module")
def team():
    mp = pytest.MonkeyPatch()
    mp.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret"))
    repo.reset()
    jobs.reset()
    for who in (ANN, ED, RAE):
        for flag in KNOWN:
            if not flag.startswith("launch."):
                flags.set(flag, who, True)
    ann, ed, rae = _client("ann"), _client("ed"), _client("rae")
    email_mod.remember_address(database, ANN, "ann@example.com")
    folder = ann.post("/projects", json={"name": "Spring", "brief": "Price first."}, headers=H).json()["project_id"]
    _join(ann, ed, "ed@example.com", "editor")
    _join(ann, rae, "rae@example.com", "reviewer", project_ids=[folder])
    yield {"ann": ann, "ed": ed, "rae": rae, "folder": folder}
    mp.undo()
    for who in (ANN, ED, RAE):
        for flag in KNOWN:
            flags.clear(flag, who)


def test_a_member_sees_the_owners_workspace_by_the_owners_address(team):
    view = team["rae"].get("/workspace").json()
    assert view["workspace"]["name"] == "ann@example.com's workspace" and not view["workspace"]["own"]
    names = [w["name"] for w in view["workspaces"]]
    assert names == ["My workspace", "ann@example.com's workspace"]      # two names, not the same one twice
    assert team["ann"].get("/workspace").json()["workspace"]["name"] == "My workspace"


def test_a_workspace_with_a_name_of_its_own_keeps_it(team):
    with database.tx() as c:
        c.execute("UPDATE workspaces SET name = ? WHERE owner = ?", ("Ann's studio", ANN))
    try:
        assert team["ed"].get("/workspace").json()["workspace"]["name"] == "Ann's studio"
    finally:
        with database.tx() as c:
            c.execute("UPDATE workspaces SET name = ? WHERE owner = ?", ("My workspace", ANN))


def test_the_brief_names_who_edited_it_by_address(team):
    folder = team["folder"]
    changed = team["ed"].patch(f"/projects/{folder}", json={"brief": "Price first, then the date."}, headers=H)
    assert changed.status_code == 200, changed.text
    page = team["ann"].get(f"/projects/{folder}").json()["project"]
    assert page["brief_edited_by"] == ED and page["brief_edited_by_name"] == "ed@example.com"
    versions = team["ann"].get(f"/projects/{folder}/briefs").json()["versions"]
    assert [v["created_by_name"] for v in versions] == ["ed@example.com", "ann@example.com"]


def test_an_owner_id_without_an_address_has_no_name():
    assert email_mod.person_address(database, "acct:nobody") is None
    assert email_mod.person_address(database, "email:sam@example.com") == "sam@example.com"
    assert email_mod.person_address(database, None) is None
