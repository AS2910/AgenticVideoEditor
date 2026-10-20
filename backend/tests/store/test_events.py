"""F7: the activity log. Written in the caller's transaction (a change that
rolls back leaves no event), listed newest first a page at a time, and 0012
moves the stage moves 0011 logged into it and back on down."""
import pytest

from app.store import briefs, events, migrate, rules, stages
from app.store.actors import VOLTAGE, Actor, user
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT, make_edit


@pytest.fixture()
def repo():
    r = ProjectRepository(Database())
    r.create_project("local", "Spring", brief="Bright.")
    r.create(make_source(project_id="p1"), TRANSCRIPT, folder_id="f1")
    return r


def _verbs(page):
    return [e["verb"] for e in page["events"]]


def test_an_event_is_written_with_the_change_or_not_at_all(repo):
    with pytest.raises(RuntimeError):
        with repo.db.tx() as c:
            briefs.save_in(c, "f1", "Changed.", "local")
            raise RuntimeError("the change fails after its event was written")
    assert briefs.current(repo.db, "f1").text == "Bright."
    assert _verbs(events.for_project(repo.db, "f1")) == ["brief.saved"]        # only the first save's


def test_each_change_writes_its_event_with_who_and_what(repo):
    db = repo.db
    repo.update_project("f1", brief="Bright and short.", by="local")
    rule = rules.add(db, "f1", "banned", {"word": "cheap"}, "local")
    rules.update(db, "f1", rule.rule_id, {"word": "cheapest"}, "local")
    rules.remove(db, "f1", rule.rule_id, "local")
    stages.move(db, "p1", "in_review", Actor("reviewer", "Meera"), "Sent")
    repo.append_edit("p1", make_edit("e1"), actor=VOLTAGE)
    assert repo.revert_edit("p1", "e1", actor=user("local"))
    assert repo.revert_edit("p1", "e1", actor=user("local"))                  # twice: one event
    repo.append_edit("p1", make_edit("e2"))                                    # no actor: not logged
    repo.set_folder("p1", None, actor=user("local"))
    page = events.for_project(db, "f1")
    assert _verbs(page) == ["video.moved_out", "edit.undone", "edit.shipped", "stage.moved", "rule.removed",
                            "rule.changed", "rule.added", "brief.saved", "brief.saved"]
    by = {e["verb"]: e for e in reversed(page["events"])}            # the newest of each verb
    assert by["brief.saved"]["target"] == "v2" and by["brief.saved"]["payload"] == {"version": 2}
    assert by["rule.changed"]["payload"]["before"] == {"word": "cheap"}
    assert (by["stage.moved"]["actor_kind"], by["stage.moved"]["actor_name"], by["stage.moved"]["payload"]) == (
        "reviewer", "Meera", {"from": "draft", "to": "in_review", "why": "Sent"})
    assert (by["edit.shipped"]["actor_kind"], by["edit.shipped"]["video_id"], by["edit.shipped"]["target"]) == ("voltage", "p1", "e1")
    assert by["video.moved_out"]["payload"] == {"to": None}
    assert all(e["workspace_id"] for e in page["events"])
    repo.set_folder("p1", "f1", actor=user("local"))
    assert _verbs(events.for_project(db, "f1", limit=1)) == ["video.moved_in"]
    assert _verbs(events.for_video(db, "p1"))[:2] == ["video.moved_in", "video.moved_out"]


def test_pages_are_newest_first_and_continue_from_next(repo):
    with repo.db.tx() as c:
        for n in range(5):
            events.record(c, "rule.added", user("local"), project_id="f1", target=f"rule{n}")
    first = events.for_project(repo.db, "f1", limit=3)
    assert [e["target"] for e in first["events"]] == ["rule4", "rule3", "rule2"] and first["next"]
    second = events.for_project(repo.db, "f1", limit=3, before=first["next"])
    assert [e["target"] for e in second["events"]] == ["rule1", "rule0", "v1"] and second["next"] is None


def test_0012_moves_the_stage_log_in_and_back_out():
    conn = migrate.connect(":memory:")
    migrate.up(conn, 11)
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript, project_id) VALUES ('p1', 'local', 'x', '{}', '{}', 'f1')")
    conn.execute("INSERT INTO stage_log (video_id, from_stage, to_stage, actor_kind, actor_name, why, at, workspace_id) "
                 "VALUES ('p1', 'draft', 'approved', 'user', 'local', 'ok', 'T', 'w1')")
    assert migrate.up(conn, 1) == {12: 1}
    assert "stage_log" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    row = conn.execute("SELECT project_id, video_id, verb, payload, at, workspace_id FROM project_events").fetchone()
    assert tuple(row) == ("f1", "p1", "stage.moved", '{"from": "draft", "to": "approved", "why": "ok"}', "T", "w1")
    assert migrate.down(conn, 1) == [12]
    assert [tuple(r) for r in conn.execute("SELECT video_id, from_stage, to_stage, actor_name, why, at FROM stage_log")] == [
        ("p1", "draft", "approved", "local", "ok", "T")]
