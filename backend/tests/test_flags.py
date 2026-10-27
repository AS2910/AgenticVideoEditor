"""Step 0 (FLAGS): feature flags, on per owner. The phase flags and every
golive.* flag are on for the default owners (AVE_FLAG_OWNERS, "local") and
off for everyone else; a stored row wins over the default."""
from fastapi.testclient import TestClient

from app.config import load_settings
from app.flags import GOLIVE_FLAGS, OFF_BY_DEFAULT, ON_BY_DEFAULT, VOICE_FLAGS, PHASE_FLAGS, FlagStore
from app.store.db import Database


def test_phase_and_golive_flags_are_on_for_the_default_owners_only():
    flags = FlagStore(Database(), ("local", "team@example.com"))
    for flag in (*PHASE_FLAGS, "golive.g2", "golive.anything"):
        assert flags.enabled(flag, "local") and flags.enabled(flag, "team@example.com")
        assert not flags.enabled(flag, "someone@example.com")
    assert not flags.enabled("made.up", "local")                    # an unknown flag is off by default
    assert flags.enabled_for("local") == sorted({*PHASE_FLAGS, *GOLIVE_FLAGS, *VOICE_FLAGS, *ON_BY_DEFAULT} - OFF_BY_DEFAULT)
    # Run 5 item 9: launch.batch_public is on for everyone, but brings nothing without a launch profile.
    assert flags.enabled_for("someone@example.com") == ["launch.batch_public"]


def test_a_stored_row_wins_over_the_default_and_clearing_it_goes_back():
    flags = FlagStore(Database(), ("local",))
    flags.set("projects.batch", "local", False)
    flags.set("projects.review", "beta@example.com", True)
    flags.set("labs.preview", "local", True)
    assert not flags.enabled("projects.batch", "local")
    assert flags.enabled("projects.review", "beta@example.com")
    assert flags.enabled_for("beta@example.com") == ["launch.batch_public", "projects.review"]
    assert "labs.preview" in flags.enabled_for("local") and "projects.batch" not in flags.enabled_for("local")
    flags.set("projects.batch", "local", True)                      # a second set updates the row
    assert flags.enabled("projects.batch", "local")
    flags.clear("projects.batch", "local")
    flags.clear("projects.review", "beta@example.com")
    assert flags.enabled("projects.batch", "local") and not flags.enabled("projects.review", "beta@example.com")


def test_the_default_owners_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("AVE_FLAG_OWNERS", raising=False)
    assert load_settings().flag_owners == ("local",)
    monkeypatch.setenv("AVE_FLAG_OWNERS", " local, a@example.com ,")
    assert load_settings().flag_owners == ("local", "a@example.com")


def test_get_me_flags_lists_the_callers_flags():
    from app.api.main import app, flags, repo
    repo.reset()
    client = TestClient(app)
    body = client.get("/me/flags").json()
    assert set(PHASE_FLAGS) <= set(body["flags"]) and "golive.g1" in body["flags"]
    flags.set("projects.reuse", "local", False)
    assert "projects.reuse" not in client.get("/me/flags").json()["flags"]
    repo.reset()                                                    # the reset forgets stored rows
    assert "projects.reuse" in client.get("/me/flags").json()["flags"]
