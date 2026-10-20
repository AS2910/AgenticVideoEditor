"""B2: the master's edit marker and the changes since a version last synced,
read from the activity log (F7)."""
from app.store import languages
from app.store.actors import user
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT, make_edit


def seeded():
    repo = ProjectRepository()
    for _ in range(2):
        pid = repo.next_id()
        repo.create(make_source(project_id=pid), TRANSCRIPT)
    repo.link_language("p2", "p1", "hi", languages.marker(repo.db, "p1"))
    return repo


def test_the_marker_moves_with_every_ship_and_undo_of_the_master_only():
    repo = seeded()
    assert languages.marker(repo.db, "p1") == 0
    repo.append_edit("p1", make_edit("e1"), actor=user("local"))
    first = languages.marker(repo.db, "p1")
    repo.append_edit("p2", make_edit("e1"), actor=user("local"))          # the version's own edit: not the master's
    assert languages.marker(repo.db, "p1") == first > 0
    repo.revert_edit("p1", "e1", actor=user("local"))
    assert languages.marker(repo.db, "p1") > first
    assert repo.get("p2").master_id == "p1" and [r.source.project_id for r in repo.language_children("p1")] == ["p2"]


def test_changes_since_are_net_and_in_order():
    repo = seeded()
    repo.append_edit("p1", make_edit("e1"), actor=user("local"))
    since = languages.marker(repo.db, "p1")
    repo.append_edit("p1", make_edit("e2"), actor=user("local"))
    repo.append_edit("p1", make_edit("e3"), actor=user("local"))
    repo.revert_edit("p1", "e3", actor=user("local"))                      # shipped and undone since: nothing changed
    repo.revert_edit("p1", "e1", actor=user("local"))                      # shipped before, undone since: a change
    got = languages.changes_since(repo.db, "p1", since)
    assert [(c["edit_id"], c["verb"]) for c in got] == [("e2", "edit.shipped"), ("e1", "edit.undone")]
