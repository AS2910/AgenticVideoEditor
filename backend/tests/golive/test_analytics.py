"""G7 store: the allow-list, once-only funnel steps, the numbers the admin
page shows (nothing invented: None until there is something under it),
the F7 log mirrored into analytics, migration 0026 up and down."""
import json

import pytest

from app import analytics
from app.store import events, migrate
from app.store.actors import Actor
from app.store.db import Database


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "t.db")


def names(db):
    with db.tx() as c:
        return [r[0] for r in c.execute("SELECT name FROM analytics_events ORDER BY id")]


def test_only_listed_names_are_written_and_first_steps_once(db):
    assert not analytics.track("made.up", "u", db=db)
    assert not analytics.track("signed_up", "", db=db)                 # no owner, no event
    assert analytics.track("signed_up", "u", db=db)
    assert not analytics.track("signed_up", "u", db=db)                # once per owner
    assert analytics.track("signed_up", "v", db=db)
    assert analytics.track("video_uploaded", "u", {"seconds": 12}, db=db)
    assert analytics.track("video_uploaded", "u", {"seconds": 12}, db=db)   # not a once-only step
    assert names(db) == ["signed_up", "signed_up", "video_uploaded", "video_uploaded"]
    # The two lists do not overlap except by design, and the client cannot post a funnel step.
    assert "take_added" not in analytics.CLIENT_NAMES and "bell.opened" in analytics.CLIENT_NAMES


def test_track_never_raises(tmp_path):
    broken = Database(tmp_path / "b.db")
    with broken.tx() as c:
        c.execute("DROP TABLE analytics_events")
    assert analytics.track("signed_up", "u", db=broken) is False


def test_numbers_are_none_until_measured(db):
    assert analytics.take_acceptance(db) == {"voiced": 0, "added": 0, "rate": None}
    cost = analytics.cost_per_exported_minute(db)
    assert cost["per_minute"] is None and cost["minutes"] == 0
    assert [s["share"] for s in analytics.funnel(db)] == [None] * len(analytics.FUNNEL)
    assert analytics.vendor_quality(db) == []


def test_funnel_acceptance_cost_and_quality(db):
    for owner in ("a", "b"):
        analytics.track("signed_up", owner, db=db)
        analytics.track("first_sign_in", owner, db=db)
    analytics.track("video_uploaded", "a", db=db)
    for i in range(4):
        analytics.track("take_voiced", "a", {"vendor": "elevenlabs", **({"sim_o": 0.8, "utmos": 4.0} if i == 0 else {})}, db=db)
    analytics.track("take_voiced", "a", {"vendor": "mock"}, db=db)
    analytics.track("take_added", "a", db=db)
    analytics.track("video_exported", "a", {"seconds": 90}, db=db)
    analytics.track("first_export", "a", db=db)
    with db.tx() as c:
        c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES ('p1', 'elevenlabs', 'speech', 1, 'characters', 0.3, 'x')")
    steps = {s["step"]: s for s in analytics.funnel(db)}
    assert steps["signed_up"]["owners"] == 2 and steps["first_export"]["owners"] == 1 and steps["first_export"]["share"] == 0.5
    assert analytics.take_acceptance(db) == {"voiced": 5, "added": 1, "rate": 0.2}
    assert analytics.cost_per_exported_minute(db) == {"cost_usd": 0.3, "minutes": 1.5, "per_minute": 0.2}
    quality = {v["vendor"]: v for v in analytics.vendor_quality(db)}
    assert quality["elevenlabs"]["sim_o"] == 0.8 and quality["elevenlabs"]["sim_o_takes"] == 1 and quality["elevenlabs"]["measured"]
    assert quality["mock"]["sim_o"] is None and quality["mock"]["utmos"] is None and not quality["mock"]["measured"]
    counted = {(c["name"], c["source"]): c["count"] for c in analytics.counts(db)}
    assert counted[("take_voiced", "server")] == 5


def test_the_activity_log_is_mirrored_in_the_same_transaction(db):
    with db.tx() as c:
        c.execute("INSERT INTO workspaces (id, name, owner, created_at) VALUES ('w1', 'Mine', 'ana', 'x')")
        events.record(c, "brief.saved", Actor("user", "ana"), project_id="f1", workspace_id="w1", payload={"version": 2, "text": "long"})
        events.record(c, "edit.shipped", Actor("user", "ana"), workspace_id="w1", payload={"overridden": False, "text": "hi"})
    assert names(db) == ["brief.saved", "edit.shipped", "take_added"]
    with db.tx() as c:
        row = c.execute("SELECT owner, workspace_id, props FROM analytics_events WHERE name = 'brief.saved'").fetchone()
    assert row["owner"] == "ana" and row["workspace_id"] == "w1"
    props = json.loads(row["props"])
    assert props["version"] == 2 and "text" not in props                 # numbers kept, free text not
    # A change that rolls back takes its event with it.
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            events.record(c, "rule.added", Actor("user", "ana"), workspace_id="w1")
            raise RuntimeError
    assert "rule.added" not in names(db)


def test_migration_0026_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "analytics_events" in tabs()
    migrate.down_to(conn, 25)   # back to 0025
    assert "analytics_events" not in tabs() and "notifications" in tabs()
    migrate.up(conn)
    assert "analytics_events" in tabs()
