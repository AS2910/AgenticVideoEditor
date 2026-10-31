"""G4 store: notifications follow each person's settings (in the app, by
email through the digest), read marks, spend thresholds once each,
migration 0025 up and down."""
from datetime import timedelta

import pytest

from app.notify import digest, inbox
from app.notify.email import OutboxEmail, outbox
from app.store import migrate
from app.store.db import Database
from app.timefmt import iso


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "t.db")


def test_defaults_and_changes_per_kind(db):
    found = {k["kind"]: (k["in_app"], k["email"]) for k in inbox.settings(db, "u")}
    assert found["job_done"] == (True, False) and found["job_failed"] == (True, True) and len(found) == 10   # run 4: consent_review, consent_decided; run 5: vendor_failure
    changed = {k["kind"]: (k["in_app"], k["email"]) for k in inbox.set_settings(db, "u", {"job_done": {"email": True}, "approval": {"in_app": False}})}
    assert changed["job_done"] == (True, True) and changed["approval"] == (False, True)
    assert {k["kind"]: (k["in_app"], k["email"]) for k in inbox.settings(db, "v")}["approval"] == (True, True)   # per person
    with pytest.raises(ValueError):
        inbox.set_settings(db, "u", {"nope": {"email": True}})


def test_a_notification_lands_in_the_app_and_the_digest_as_set(db):
    inbox.add(db, "u", "job_failed", "The export of ad.mp4 failed.", body="ffmpeg stopped.", link="#v/p1")
    inbox.set_settings(db, "u", {"job_done": {"in_app": False}})
    assert inbox.add(db, "u", "job_done", "The check is done.") is None              # in-app off: no row
    items = inbox.list_for(db, "u")
    assert [(i["kind"], i["title"], i["read"]) for i in items] == [("job_failed", "The export of ad.mp4 failed.", False)]
    assert [p["kind"] for p in digest.pending(db, "u")] == ["job_failed"]          # email on: one digest item
    sent = digest.flush(db, OutboxEmail(db), digest.utcnow() + timedelta(minutes=11), lambda o: "u@x.io")
    assert len(sent) == 1 and "The export of ad.mp4 failed. ffmpeg stopped." in sent[0].body
    assert "Here is what happened in Voltage." in sent[0].body and outbox(db)[0]["to_addr"] == "u@x.io"


def test_read_marks(db):
    ids = [inbox.add(db, "u", "spend_alert", f"Alert {n}") for n in range(3)]
    inbox.add(db, "w", "spend_alert", "Theirs")
    assert inbox.unread(db, "u") == 3
    assert inbox.mark_read(db, "u", [ids[0], 999]) == 1 and inbox.unread(db, "u") == 2
    assert inbox.mark_read(db, "u", None) == 2 and inbox.unread(db, "u") == 0 and inbox.unread(db, "w") == 1


def test_spend_thresholds_are_said_once_each(db):
    assert [inbox.crossed(s, 10) for s in (4.9, 5, 7.99, 8, 9.99, 10, 12)] == [None, 50, 50, 80, 80, 100, 100]
    assert inbox.crossed(5, None) is None
    with db.tx() as c:
        assert inbox.spend_alert_once(c, "u", "month", "u", "2026-10:100", 50)
        assert not inbox.spend_alert_once(c, "u", "month", "u", "2026-10:100", 50)
        assert inbox.spend_alert_once(c, "u", "month", "u", "2026-10:100", 100)
        assert not inbox.spend_alert_once(c, "u", "month", "u", "2026-10:100", 80)    # marked on the way to 100
        assert inbox.spend_alert_once(c, "u", "month", "u", "2026-11:100", 50)        # a new month starts again


def test_migration_0025_up_and_down(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    mine = {"notifications", "notification_settings", "spend_alerts"}
    assert mine <= tabs()
    migrate.down_to(conn, 24)   # back to 0024
    assert not (mine & tabs()) and "workspace_members" in tabs()
    migrate.up(conn)
    assert mine <= tabs()


def test_the_held_line_kinds_are_listed_only_under_voice_consent(db):
    """Voice consent V1 step 6: line_review (admins) and line_decided are in the settings list with the flag on."""
    off = [k["kind"] for k in inbox.settings(db, "u", admin=True)]
    assert "line_review" not in off and "line_decided" not in off
    on = [k["kind"] for k in inbox.settings(db, "u", admin=True, consent=True)]
    assert on[-2:] == ["line_review", "line_decided"]
    mine = [k["kind"] for k in inbox.settings(db, "u", admin=False, consent=True)]
    assert "line_decided" in mine and "line_review" not in mine
    with pytest.raises(ValueError):
        inbox.set_settings(db, "u", {"line_decided": {"email": False}})
    changed = {k["kind"]: k["email"] for k in inbox.set_settings(db, "u", {"line_decided": {"email": False}}, admin=False, consent=True)}
    assert changed["line_decided"] is False
