"""C2: review comments: kept at their time and version, replies append,
resolve and reopen, open counts per video; refusals say why."""
import pytest

from app.store import comments
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT


@pytest.fixture()
def db():
    r = ProjectRepository(Database())
    r.create(make_source(project_id="p1"), TRANSCRIPT)
    r.create(make_source(project_id="p2"), TRANSCRIPT)
    return r.db


def add(db, **kw):
    with db.tx() as c:
        return comments.add_in(c, **{"video_id": "p1", "author_name": "Priya", "at_s": 1.0, "text": "Hi", **kw})


def test_a_comment_keeps_its_time_version_and_link(db):
    made = add(db, at_s=12.345, version=4, share_id="sh1", text="  Logo bigger  ", author_name="  Priya   S ")
    assert (made.at_s, made.version, made.share_id, made.text, made.author_name, made.status) == (
        12.35, 4, "sh1", "Logo bigger", "Priya S", "open")
    add(db, at_s=3.0)
    assert [c.at_s for c in comments.for_video(db, "p1")] == [3.0, 12.35]            # in time order
    assert [c.comment_id for c in comments.for_share(db, "sh1")] == [made.comment_id]


def test_replies_append_and_resolve_reopens(db):
    made = add(db)
    with db.tx() as c:
        comments.reply_in(c, made.comment_id, "user", "local", "On it.")
        after = comments.reply_in(c, made.comment_id, "reviewer", "Priya", "Thanks")
    assert [(r["author_kind"], r["text"]) for r in after.replies] == [("user", "On it."), ("reviewer", "Thanks")]
    with db.tx() as c:
        done = comments.set_status_in(c, made.comment_id, True, "local")
    assert done.status == "resolved" and done.resolved_by == "local" and comments.open_counts(db, ["p1"]) == {}
    with db.tx() as c:
        again = comments.set_status_in(c, made.comment_id, False, "local")
    assert again.status == "open" and again.resolved_at is None


def test_open_counts_per_video(db):
    add(db)
    add(db)
    add(db, video_id="p2")
    assert comments.open_counts(db, ["p1", "p2", "p9"]) == {"p1": 2, "p2": 1}
    assert comments.open_counts(db, []) == {}


@pytest.mark.parametrize("kw, says", [
    ({"text": "   "}, "Write something first."),
    ({"text": "x" * 2001}, "Keep it under 2000 characters."),
    ({"at_s": -1}, "A comment sits at a time in the video."),
    ({"video_id": "p9"}, "That video is not here any more."),
])
def test_refusals_say_why(db, kw, says):
    with pytest.raises(comments.CommentError, match=says):
        add(db, **kw)
