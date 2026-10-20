"""F2: brief versions. Every save is a version, the project points at the
current one, projects.brief stays as its alias, and 0009 makes version 1
from the brief a project already has."""
import os
import shutil

import pytest

from app.store import briefs, migrate
from app.store.db import Database
from app.store.repository import ProjectRepository

AT = "2026-10-20T00:00:00.000Z"


@pytest.fixture()
def repo():
    return ProjectRepository(Database())


def test_saving_a_brief_makes_a_new_version_and_the_project_points_at_it(repo):
    project = repo.create_project("local", "Spring", brief="Bright and short.")
    assert project.brief == "Bright and short." and project.brief_version == 1
    changed = repo.update_project(project.project_id, brief="Bright, short, price first.", by="ashish")
    assert changed.brief == "Bright, short, price first." and changed.brief_version == 2
    now = briefs.current(repo.db, project.project_id)
    assert (now.version, now.text, now.created_by) == (2, "Bright, short, price first.", "ashish")
    assert [v.version for v in briefs.history(repo.db, project.project_id)] == [2, 1]
    assert briefs.history(repo.db, project.project_id)[1].created_by == "local"


def test_the_same_words_twice_are_one_version_and_other_fields_make_none(repo):
    project = repo.create_project("local", "Spring", brief="Bright.")
    repo.update_project(project.project_id, brief="Bright.")
    repo.update_project(project.project_id, name="Spring sale")
    assert [v.version for v in briefs.history(repo.db, project.project_id)] == [1]


def test_a_project_with_no_brief_has_no_version_until_one_is_written(repo):
    project = repo.create_project("local", "Empty")
    assert project.brief_version is None and briefs.current(repo.db, project.project_id) is None
    assert repo.update_project(project.project_id, brief="").brief_version is None
    first = repo.update_project(project.project_id, brief="Now a brief.")
    assert first.brief_version == 1
    cleared = repo.update_project(project.project_id, brief="")
    assert cleared.brief == "" and cleared.brief_version == 2      # clearing it is a version too


def test_save_returns_none_for_a_missing_project(repo):
    assert briefs.save(repo.db, "f99", "x", "local") is None


def test_diff_is_word_level_plain_data(repo):
    project = repo.create_project("local", "Spring", brief="Get 30% off this Diwali.")
    repo.update_project(project.project_id, brief="Get 40% off this Diwali, today only.")
    runs = briefs.diff(repo.db, project.project_id, 1, 2)
    assert runs == [{"op": "same", "text": "Get "}, {"op": "removed", "text": "30%"}, {"op": "added", "text": "40%"},
                    {"op": "same", "text": " off this "}, {"op": "removed", "text": "Diwali."},
                    {"op": "added", "text": "Diwali, today only."}]
    assert briefs.diff(repo.db, project.project_id, 0, 1) == [{"op": "added", "text": "Get 30% off this Diwali."}]
    assert briefs.diff(repo.db, project.project_id, 1, 7) is None


def _at_0008(conn):
    migrate.up(conn, 8)
    conn.execute("INSERT INTO projects (id, owner, name, brief, created_at, workspace_id) VALUES ('f1', 'local', 'A', 'Price first.', ?, 'w1')", (AT,))
    conn.execute("INSERT INTO projects (id, owner, name, brief, created_at, workspace_id) VALUES ('f2', 'local', 'B', '', ?, 'w1')", (AT,))


def test_0009_makes_version_1_from_the_brief_a_project_has_and_down_keeps_the_text():
    conn = migrate.connect(":memory:")
    _at_0008(conn)
    assert migrate.up(conn, 1) == {9: 1}
    rows = [tuple(r) for r in conn.execute("SELECT project_id, version, text, created_by, created_at, workspace_id FROM project_briefs")]
    assert rows == [("f1", 1, "Price first.", "local", AT, "w1")]
    assert [tuple(r) for r in conn.execute("SELECT id, brief, brief_version FROM projects ORDER BY id")] == [
        ("f1", "Price first.", 1), ("f2", "", None)]
    assert migrate.down(conn, 1) == [9]
    assert "brief_version" not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
    assert [tuple(r) for r in conn.execute("SELECT id, brief FROM projects ORDER BY id")] == [("f1", "Price first."), ("f2", "")]
    migrate.up(conn, 1)
    assert conn.execute("SELECT COUNT(*) FROM project_briefs").fetchone()[0] == 1


@pytest.mark.skipif(not os.environ.get("AVE_LIVE_DB_COPY"), reason="set AVE_LIVE_DB_COPY to a copy of a real database")
def test_0009_on_a_copy_of_a_real_database(tmp_path):
    path = tmp_path / "copy.db"
    shutil.copy(os.environ["AVE_LIVE_DB_COPY"], path)
    conn = migrate.connect(str(path))
    migrate.up(conn, len([v for v in range(1, 9) if v not in migrate.applied(conn)]))   # up to 0008
    briefs_before = {r[0]: r[1] for r in conn.execute("SELECT id, brief FROM projects")}
    migrate.up(conn, 1)
    for pid, text in briefs_before.items():
        row = conn.execute("SELECT text FROM project_briefs b JOIN projects p ON p.id = b.project_id "
                           "AND p.brief_version = b.version WHERE p.id = ?", (pid,)).fetchone()
        assert (row[0] if row else "") == (text if text.strip() else ""), pid
    migrate.down(conn, 1)
    assert {r[0]: r[1] for r in conn.execute("SELECT id, brief FROM projects")} == briefs_before
