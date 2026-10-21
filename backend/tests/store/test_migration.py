"""Folders: a database made before projects were folders is renamed at
startup; every project row becomes a standalone video."""
import sqlite3

import pytest

from app.store.db import Database
from app.store.repository import ProjectRepository


OLD_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE projects (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL,
    transcript TEXT NOT NULL, consent_at TEXT, candidate_counter INTEGER NOT NULL DEFAULT 0,
    speakers TEXT NOT NULL DEFAULT '{}', settings TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX projects_by_owner ON projects (owner, created_at);
CREATE TABLE usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, vendor TEXT NOT NULL, what TEXT NOT NULL,
    units REAL NOT NULL, unit TEXT NOT NULL, usd REAL NOT NULL, at TEXT NOT NULL
);
CREATE TABLE messages (project_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (project_id, seq));
"""

SOURCE = '{"project_id": "p1", "filename": "ad.mp4", "duration": 2.3, "media": {"kind": "video", "sha256": "%s", "path": "/x", "duration": 2.3, "container": "mp4"}}' % ("a" * 64)
TRANSCRIPT = '{"words": [], "statements": []}'


def _old_database(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO meta VALUES ('project_counter', '1')")
    conn.execute("INSERT INTO projects (id, owner, created_at, source, transcript) VALUES ('p1', 'local', '2026-01-01T00:00:00+00:00', ?, ?)",
                 (SOURCE, TRANSCRIPT))
    conn.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES ('p1', 'openai', 'transcription', 1, 'minutes', 0.006, '2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO messages VALUES ('p1', 1, 'user', 'hi', '2026-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()


@pytest.mark.sqlite_only
def test_projects_table_is_renamed_to_videos_and_every_row_is_standalone(tmp_path):
    path = tmp_path / "ave.db"
    _old_database(path)

    db = Database(path)

    assert db.migrated_projects_to_videos is True
    repo = ProjectRepository(db)
    record = repo.get("p1")
    assert record is not None and record.source.filename == "ad.mp4" and record.folder_id is None
    assert [r.source.project_id for r in repo.list("local")] == ["p1"]
    assert repo.list("local", folder=None) and repo.list("local", folder="f1") == []
    # The new columns and the folder table are there; the ledger row survived.
    with db.tx() as c:
        video_columns = {r["name"] for r in c.execute("PRAGMA table_info(videos)")}
        usage_columns = {r["name"] for r in c.execute("PRAGMA table_info(usage)")}
        folder_columns = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert c.execute("SELECT COUNT(*) FROM usage WHERE project_id = 'p1'").fetchone()[0] == 1
    assert {"videos", "projects", "usage", "messages", "meta"} <= tables
    assert "project_id" in video_columns and "folder_id" in usage_columns
    assert {"id", "owner", "name", "brief", "settings", "ceiling_usd", "created_at"} <= folder_columns
    assert {"videos_by_owner", "projects_by_owner"} <= indexes
    # The id counter carries on: the next video is p2, not a reused p1.
    assert repo.next_id() == "p2"
    # Opening it again does nothing more.
    assert Database(path).migrated_projects_to_videos is False


def test_a_fresh_database_needs_no_migration_and_folder_ids_count_from_their_own_counter():
    db = Database(":memory:")
    assert db.migrated_projects_to_videos is False
    repo = ProjectRepository(db)
    first = repo.create_project("local", "Spring sale", "Bright and short.")
    second = repo.create_project("local", "Autumn")
    assert (first.project_id, second.project_id, repo.next_id()) == ("f1", "f2", "p1")
    assert first.brief == "Bright and short." and first.settings == {} and first.ceiling_usd is None
    assert [p.name for p in repo.list_projects("local")] == ["Spring sale", "Autumn"]
    updated = repo.update_project("f1", brief="Longer.", settings={"autonomy": "draft"}, ceiling_usd=5.0)
    assert (updated.brief, updated.settings, updated.ceiling_usd) == ("Longer.", {"autonomy": "draft"}, 5.0)
    assert repo.update_project("f1", clear_ceiling=True).ceiling_usd is None
    # Deleting a folder with `keep` makes its videos standalone and drops its meta lists.
    repo.set_meta_list("project_voices:f1", [{"voice_id": "v"}])
    assert repo.delete_project("f1", keep_videos=True) and repo.get_project("f1") is None
    assert repo.meta_list("project_voices:f1") == []
    # A reset forgets the folder counter too.
    repo.reset()
    assert repo.create_project("local", "Again").project_id == "f1"
