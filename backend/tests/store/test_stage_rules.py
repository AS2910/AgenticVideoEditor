"""C1: the automatic stage moves. A new edit on an Approved video takes it
back to Draft in the edit's own transaction, logged; a review link puts
videos In review; a reviewer's answer is logged under their name."""
from app.domain.models import Transcript
from app.store import events, stages
from app.store.actors import VOLTAGE, user
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import make_edit


def _repo():
    db = Database(":memory:")
    repo = ProjectRepository(db)
    repo.create(make_source(project_id="p1"), Transcript(words=()))
    repo.create(make_source(project_id="p2"), Transcript(words=()))
    return db, repo


def _ship(repo, edit_id="e1", actor=VOLTAGE):
    repo.append_edit("p1", make_edit(edit_id), actor=actor)


def test_an_edit_on_an_approved_video_drops_it_to_draft_and_logs_it():
    db, repo = _repo()
    stages.move(db, "p1", "approved", user("local"))
    _ship(repo)
    assert stages.current(db, "p1") == "draft"
    log = events.for_video(db, "p1")["events"]
    assert [e["verb"] for e in log[:2]] == ["stage.moved", "edit.shipped"]
    assert log[0]["actor_kind"] == "voltage" and log[0]["payload"]["from"] == "approved"
    assert log[0]["payload"]["why"] == "A new edit was added after approval."


def test_an_edit_on_any_other_stage_leaves_it_where_it_is():
    db, repo = _repo()
    for stage in ("draft", "in_review", "changes_asked", "exported"):
        stages.move(db, "p1", stage, user("local"))
        _ship(repo, edit_id=f"e-{stage}", actor=user("local"))
        assert stages.current(db, "p1") == stage


def test_a_review_link_puts_videos_in_review_and_a_reviewer_answers_under_their_name():
    db, _ = _repo()
    stages.move(db, "p2", "in_review", user("local"))
    moved = stages.review_sent(db, ["p1", "p2", "gone"], user("local"), "Review link sent to Priya.")
    assert [(m.video_id, m.to_stage) for m in moved] == [("p1", "in_review")]       # p2 was there already
    assert stages.reviewer_approved(db, "p1", "Priya", version=5).why == "Approved v5 by review link."
    assert stages.current(db, "p1") == "approved"
    last = events.for_video(db, "p1", limit=1)["events"][0]
    assert (last["actor_kind"], last["actor_name"], last["payload"]["to"]) == ("reviewer", "Priya", "approved")
    assert stages.reviewer_asked_changes(db, "p2", "").actor_name == "A reviewer"
    assert stages.current(db, "p2") == "changes_asked"
