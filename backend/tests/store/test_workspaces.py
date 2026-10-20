"""Step 0 (WS): workspaces. Every user-data row names a workspace, the
owner's own; 0008 backfills existing rows; every write sets it; down drops it."""
import os
import shutil

import pytest

from app.budget import VoiceBudget
from app.domain.plan import Plan
from app.jobs.activity import ActivityJobs
from app.store import migrate
from app.store.db import Database
from app.store.migrations.m0008_workspaces import BY_VIDEO, OWNED
from app.store.repository import ProjectRepository
from app.usage import Ledger
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT, make_candidate, make_edit

TABLES = (*OWNED, *BY_VIDEO)
AT = "2026-10-20T00:00:00.000Z"


def _seed_before_workspaces(conn):
    """A database at 0007 with two owners, a project-level charge and an orphan row."""
    migrate.up(conn, 7)
    for vid, owner, folder in (("p1", "local", "f1"), ("p2", "local", None), ("p3", "b@example.com", None)):
        conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript, project_id) VALUES (?, ?, ?, '{}', '{}', ?)",
                     (vid, owner, AT, folder))
    conn.execute("INSERT INTO projects (id, owner, name, created_at) VALUES ('f1', 'local', 'Spring', ?)", (AT,))
    conn.execute("INSERT INTO projects (id, owner, name, created_at) VALUES ('f2', 'c@example.com', 'Empty', ?)", (AT,))
    for vid in ("p1", "p3"):
        conn.execute("INSERT INTO candidates VALUES (?, 'c1', '{}')", (vid,))
        conn.execute("INSERT INTO edits VALUES (?, 1, '{}')", (vid,))
        conn.execute("INSERT INTO messages (project_id, seq, role, text, at) VALUES (?, 1, 'user', 'hi', ?)", (vid, AT))
        conn.execute("INSERT INTO turns VALUES (?, 1, 'user', '\"hi\"', ?)", (vid, AT))
        conn.execute("INSERT INTO plans VALUES (?, 'plan1', 1, '{}')", (vid,))
        conn.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES (?, 'openai', 't', 1, 'minutes', 0.01, ?)", (vid, AT))
        conn.execute("INSERT INTO jobs (job_id, project_id, kind, status, touched, body) VALUES (?, ?, 'mix', 'done', 0, '{}')", (f"J{vid}", vid))
    # A project-level charge (no video) and a charge whose video is gone.
    conn.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at, folder_id) VALUES ('', 'elevenlabs', 'design', 1, 'calls', 0.1, ?, 'f1')", (AT,))
    conn.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES ('p99', 'openai', 't', 1, 'minutes', 0.01, ?)", (AT,))


def _ws(conn, table, where="1=1"):
    return [r[0] for r in conn.execute(f"SELECT workspace_id FROM {table} WHERE {where} ORDER BY rowid")]


def test_the_backfill_gives_every_row_its_owners_own_workspace():
    conn = migrate.connect(":memory:")
    _seed_before_workspaces(conn)
    ran = migrate.up(conn)
    assert list(ran) == [8] and ran[8] > 0
    spaces = {r["owner"]: r["id"] for r in conn.execute("SELECT * FROM workspaces")}
    assert set(spaces) == {"local", "b@example.com", "c@example.com"}  # one each, an empty project's owner too
    mine, theirs = spaces["local"], spaces["b@example.com"]
    assert _ws(conn, "videos") == [mine, mine, theirs]
    assert _ws(conn, "projects") == [mine, spaces["c@example.com"]]
    for table in ("candidates", "edits", "messages", "turns", "plans", "jobs"):
        assert _ws(conn, table) == [mine, theirs], table
    assert _ws(conn, "usage") == [mine, theirs, mine, None]        # the project-level charge takes its project's; the orphan none
    assert migrate.up(conn) == {}


def test_down_drops_the_table_and_every_column_and_up_backfills_the_same_again():
    conn = migrate.connect(":memory:")
    _seed_before_workspaces(conn)
    migrate.up(conn)
    first = {t: _ws(conn, t) for t in TABLES}
    assert migrate.down(conn, 1) == [8]
    assert "workspaces" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in TABLES:
        assert "workspace_id" not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}, table
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 4    # no row lost
    migrate.up(conn)
    assert {t: _ws(conn, t) for t in TABLES} == first


def test_every_write_sets_the_workspace():
    db = Database()
    repo = ProjectRepository(db)
    ledger = Ledger(db)
    activity = ActivityJobs(db)
    folder = repo.create_project("local", "Spring")
    repo.create(make_source(project_id="p1"), TRANSCRIPT, owner="local", folder_id=folder.project_id)
    repo.create(make_source(project_id="p2"), TRANSCRIPT, owner="b@example.com")
    for vid in ("p1", "p2"):
        repo.save_candidate(vid, make_candidate("c1"))
        repo.append_edit(vid, make_edit("e1"))
        repo.add_message(vid, "user", "hi")
        repo.append_turn(vid, "user", "hi")
        repo.save_plan(Plan("plan1", vid, "goal", "summary", ()))
        ledger.record(vid, "openai", "transcription", 1, "minutes", 0.01)
        activity.create(vid, "mix")
    VoiceBudget(1000, ledger=ledger).charge("p1", 10)
    ledger.record_project_level(folder.project_id, "elevenlabs", "design", 1, "calls", 0.1)
    repo.save_candidate("p1", make_candidate("c1"))                 # a replace keeps it

    with db.tx() as c:
        spaces = {r["owner"]: r["id"] for r in c.execute("SELECT * FROM workspaces")}
        mine, theirs = spaces["local"], spaces["b@example.com"]
        assert mine != theirs
        assert _ws(c, "projects") == [mine] and _ws(c, "videos") == [mine, theirs]
        for table in ("edits", "messages", "turns", "plans", "jobs"):
            assert _ws(c, table) == [mine, theirs], table
        assert sorted(_ws(c, "candidates")) == sorted([mine, theirs])
        assert _ws(c, "usage") == [mine, theirs, mine, mine]
    # Reads are unchanged: nothing filters on it yet (G5).
    assert [r.source.project_id for r in repo.list("local")] == ["p1"]


def test_an_owner_keeps_one_workspace():
    db = Database()
    repo = ProjectRepository(db)
    repo.create_project("local", "One")
    repo.create_project("local", "Two")
    repo.create(make_source(project_id="p1"), TRANSCRIPT)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1
        assert c.execute("SELECT name FROM workspaces").fetchone()[0] == "My workspace"


@pytest.mark.skipif(not os.environ.get("AVE_LIVE_DB_COPY"), reason="set AVE_LIVE_DB_COPY to a copy of a real database")
def test_the_backfill_on_a_copy_of_a_real_database(tmp_path):
    path = tmp_path / "copy.db"
    shutil.copy(os.environ["AVE_LIVE_DB_COPY"], path)
    conn = migrate.connect(str(path))
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    migrate.up(conn)
    assert {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES} == counts
    owners = {r[0] for r in conn.execute("SELECT owner FROM videos UNION SELECT owner FROM projects")}
    assert {r[0] for r in conn.execute("SELECT owner FROM workspaces")} == owners
    for table in OWNED:
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id IS NULL").fetchone()[0] == 0
    for table in BY_VIDEO:
        # Only rows whose video (and project) are gone may stay without one.
        stray = conn.execute(f"SELECT COUNT(*) FROM {table} t WHERE workspace_id IS NULL AND EXISTS "
                             f"(SELECT 1 FROM videos v WHERE v.id = t.project_id)").fetchone()[0]
        assert stray == 0, table
