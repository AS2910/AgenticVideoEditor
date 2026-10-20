"""F5: a video's stage. Draft by default; moved only through stages.move,
which validates and logs who, when and why; an Approved video drops to
Draft on a new edit (the rule C1 calls); 0011 goes down and up."""
import pytest

from app.store import migrate, stages
from app.store.actors import VOLTAGE, Actor, user
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT


@pytest.fixture()
def repo():
    r = ProjectRepository(Database())
    r.create(make_source(project_id="p1"), TRANSCRIPT)
    return r


def test_a_new_video_is_a_draft(repo):
    assert repo.get("p1").stage == "draft" and stages.current(repo.db, "p1") == "draft"
    assert stages.current(repo.db, "p9") is None


def test_a_move_is_validated_and_logged_with_who_when_and_why(repo):
    moved = stages.move(repo.db, "p1", "in_review", user("local"), "  Sent   to the client ")
    assert (moved.from_stage, moved.to_stage, moved.actor_kind, moved.actor_name, moved.why) == (
        "draft", "in_review", "user", "local", "Sent to the client")
    assert moved.at and repo.get("p1").stage == "in_review"
    assert stages.move(repo.db, "p1", "in_review", user("local")) is None          # already there: no move, no log
    stages.move(repo.db, "p1", "approved", Actor("reviewer", "Meera"))
    assert [(m.to_stage, m.actor_name) for m in stages.history(repo.db, "p1")] == [("approved", "Meera"), ("in_review", "local")]
    with pytest.raises(stages.StageError, match="one of"):
        stages.move(repo.db, "p1", "shipped", user("local"))
    with pytest.raises(stages.StageError, match="No such video"):
        stages.move(repo.db, "p9", "draft", user("local"))
    with pytest.raises(ValueError):
        Actor("robot", "x")


def test_a_new_edit_on_an_approved_video_moves_it_to_draft(repo):
    assert stages.after_new_edit(repo.db, "p1", VOLTAGE) is None                   # a draft stays a draft
    stages.move(repo.db, "p1", "approved", user("local"))
    back = stages.after_new_edit(repo.db, "p1", VOLTAGE)
    assert (back.from_stage, back.to_stage, back.actor_kind) == ("approved", "draft", "voltage")
    assert "after approval" in back.why and repo.get("p1").stage == "draft"


def test_0011_goes_down_and_up_keeping_every_video():
    conn = migrate.connect(":memory:")
    migrate.up(conn, 10)
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript) VALUES ('p1', 'local', 'x', '{}', '{}')")
    assert list(migrate.up(conn, 1)) == [11]
    assert conn.execute("SELECT stage FROM videos").fetchone()[0] == "draft"
    assert migrate.down(conn, 1) == [11]
    assert "stage" not in {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
