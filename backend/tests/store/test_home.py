"""D4: the transcript matcher, archive and pins in the store, and
migration 0021 (pins, projects.archived_at) up, down and its refusal."""
import pytest

from app.store import home, migrate
from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT

WORDS = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, t in enumerate(
    "Get thirty percent off, this Diwali only. Thirty percent!".split())]


def test_transcript_hits_match_words_in_order_ignoring_case_and_punctuation():
    hits = home.transcript_hits(WORDS, "THIRTY percent")
    assert [h["at"] for h in hits] == [0.5, 3.5]
    assert hits[0]["match"] == "thirty percent" and "Get thirty percent off," in hits[0]["text"]
    assert [h["at"] for h in home.transcript_hits(WORDS, "diw")] == [2.5]      # the last word may be a start
    assert home.transcript_hits(WORDS, "percent thirty") == []
    assert home.transcript_hits(WORDS, "  ") == []
    assert len(home.transcript_hits(WORDS * 3, "thirty", limit=2)) == 2


@pytest.fixture()
def repo(tmp_path):
    repo = ProjectRepository(Database(tmp_path / "ave.db"))
    repo.create_project("local", "Spring")
    repo.create(make_source(project_id="p1", filename="ad.mp4"), TRANSCRIPT, folder_id="f1")
    return repo


def test_archive_and_pins(repo):
    assert home.set_archived(repo.db, "f1", "local", True) and not home.set_archived(repo.db, "f1", "local", True)
    assert home.archived_project_of(repo.db, video_id="p1") == {"id": "f1", "owner": "local"}
    assert repo.get_project("f1").archived_at
    assert home.archived_projects(repo.db, "local") == {"f1"}
    assert home.set_archived(repo.db, "f1", "local", False)
    assert home.archived_project_of(repo.db, project_id="f1") is None
    assert home.pin(repo.db, "local", "video", "p1") and not home.pin(repo.db, "local", "video", "p1")
    assert home.pin(repo.db, "local", "project", "f1")
    with pytest.raises(home.NotFound):
        home.pin(repo.db, "other", "project", "f1")
    assert [p["id"] for p in home.pins(repo.db, "local")] == ["p1", "f1"]
    assert home.unpin(repo.db, "local", "video", "p1") and not home.unpin(repo.db, "local", "video", "p1")


def test_migration_0021_up_down_and_refuses_to_unarchive_silently(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    migrate.down(conn, max(migrate.applied(conn)) - 21)   # 0021 is the last step applied
    cols = lambda: {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
    tabs = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"archived_at", "archived_by"} <= cols() and "pins" in tabs()
    conn.execute("INSERT INTO projects (id, owner, name, brief, settings, created_at, archived_at) "
                 "VALUES ('f1', 'local', 'Spring', '', '{}', 'x', 'y')")
    conn.commit()
    with pytest.raises(RuntimeError):
        migrate.down(conn, 1)
    conn.execute("UPDATE projects SET archived_at = NULL")
    conn.commit()
    migrate.down(conn, 1)
    assert "archived_at" not in cols() and "pins" not in tabs()
    migrate.up(conn)
    assert "archived_at" in cols() and "pins" in tabs()
