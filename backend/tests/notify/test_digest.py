"""C2: the owner's digest batches news for 10 minutes from the first item,
one email per owner, through the email interface (the fake outbox)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.notify import digest, email
from app.store.db import Database
from app.store.repository import ProjectRepository
from app.timefmt import iso
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT

T0 = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    r = ProjectRepository(Database())
    r.create(make_source(project_id="p1"), TRANSCRIPT)
    return r.db


def queue(db, minutes, kind="comment", owner="local", **payload):
    with db.tx() as c:
        digest.queue_in(c, owner, kind, project_id="f1", video_id="p1", at=iso(T0 + timedelta(minutes=minutes)),
                        payload={"by": "Priya", "video": "ad.mp4", **payload})


def flush(db, minutes):
    return digest.flush(db, email.OutboxEmail(db), T0 + timedelta(minutes=minutes),
                        lambda owner: {"local": "me@agency.example"}.get(owner), lambda item: "http://x/#p/f1")


def test_news_within_ten_minutes_is_one_email_sent_ten_minutes_after_the_first(db):
    queue(db, 0, at_s=12, version=4, text="Logo bigger")
    queue(db, 3, "approved", version=4)
    queue(db, 9, "changes_asked", version=4, note="Shorter")
    assert flush(db, 9.9) == []
    [sent] = flush(db, 10)
    assert (sent.to, sent.kind, sent.subject) == ("me@agency.example", "digest", "3 updates from your reviewers")
    assert sent.body.splitlines()[2:5] == [
        '- Priya commented on ad.mp4 at 0:12 (v4): "Logo bigger"',
        "- Priya approved ad.mp4 v4.",
        '- Priya asked for changes on ad.mp4 v4: "Shorter"',
    ]
    assert "\nOpen the project: http://x/#p/f1\n" in sent.body and sent.html and "http://x/#p/f1" in sent.html
    assert [r["subject"] for r in email.outbox(db)] == ["3 updates from your reviewers"]
    assert flush(db, 30) == [] and digest.pending(db) == []


def test_news_after_a_digest_waits_for_its_own_ten_minutes(db):
    queue(db, 0)
    assert len(flush(db, 10)) == 1
    queue(db, 11, "approved")
    assert flush(db, 20) == []
    [sent] = flush(db, 21)
    assert sent.subject == "Priya approved ad.mp4"


def test_each_owner_gets_their_own_digest_and_an_unknown_address_still_lands_in_the_outbox(db):
    queue(db, 0)
    queue(db, 1, owner="g-123")
    sent = flush(db, 12)
    assert sorted(e.to for e in sent) == ["me@agency.example", "owner:g-123"]


def test_a_real_provider_name_falls_back_to_the_outbox(db):
    sender = email.sender_for("postmark", db)
    sender.send(email.Email(to="a@b.co", subject="Hi", body="Body", kind="version_ready"))
    assert [r["provider"] for r in email.outbox(db)] == ["outbox"]


def test_the_scheduler_ticks_until_stopped():
    import threading
    ticked = threading.Event()
    s = digest.DigestScheduler(ticked.set, every=0.01)
    s.start()
    assert ticked.wait(5)
    s.stop()


def test_addresses_are_remembered_and_checked(db):
    email.remember_address(db, "g-1", "not an email")
    assert email.address_for(db, "g-1") is None and email.address_for(db, "g-1", "fallback@x.io") == "fallback@x.io"
    email.remember_address(db, "g-1", "me@x.io")
    assert email.address_for(db, "g-1", "fallback@x.io") == "me@x.io"
