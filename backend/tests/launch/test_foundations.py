"""Launch item 1: the migration runner owns the schema, every table holding a
user's data names its workspace (defaulting to the owner's), and launch
switches are flags that can be set for everyone at once."""
import sqlite3

import pytest

from app.flags import ALL, FlagStore, main as flags_main
from app.store import migrate
from app.store.db import Database
from app.store.migrations import m0030_workspace_everywhere as m30
from app.store.workspaces import personal


def _cols(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


# FTS5 keeps each virtual table's data in shadow tables (`<name>_data`, `_idx`,
# `_content`, `_docsize`, `_config`): SQLite's own system tables, not user
# tables. The virtual table itself (9d's `search_fts`) carries the column.
FTS_SHADOWS = ("_data", "_idx", "_content", "_docsize", "_config")


def _fts_shadow(c, table):
    virtual = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL TABLE%'")}
    return any(table.endswith(s) and table[:-len(s)] in virtual for s in FTS_SHADOWS)


def test_every_user_data_table_has_a_workspace_column():
    db = Database()
    with db.tx() as c:
        missing = [t for t in m30.user_tables(c) if not _fts_shadow(c, t) and "workspace_id" not in _cols(c, t)]
    assert missing == []
    with db.tx() as c:
        assert "workspace_id" in _cols(c, "search_fts") and _fts_shadow(c, "search_fts_data")


def test_a_row_written_without_a_workspace_takes_its_owners():
    db = Database()
    with db.tx() as c:
        ws = personal(c, "google:ann")
        c.execute("INSERT INTO credit_grants (owner, kind, credits, period, reference, at) "
                  "VALUES ('google:ann', 'trial', 5, '2026-11', '', '2026-11-04T00:00:00.000Z')")
        c.execute("INSERT INTO error_reports (owner, source, message, stack, location, context, at) "
                  "VALUES ('google:ann', 'server', 'x', '', '', '{}', '2026-11-04T00:00:00.000Z')")
        assert [r[0] for r in c.execute("SELECT workspace_id FROM credit_grants")] == [ws]
        assert [r[0] for r in c.execute("SELECT workspace_id FROM error_reports")] == [ws]


def test_a_row_keyed_by_a_video_takes_the_videos_workspace():
    db = Database()
    with db.tx() as c:
        c.execute("INSERT INTO workspaces (id, name, owner, created_at) VALUES ('w9', 'x', 'google:bo', '2026')")
        c.execute("INSERT INTO videos (id, owner, created_at, source, transcript, workspace_id) "
                  "VALUES ('p1', 'google:bo', '2026', '{}', '{}', 'w9')")
        c.execute("INSERT INTO messages (project_id, seq, role, text, at) VALUES ('p1', 1, 'user', 'hi', '2026')")
        assert c.execute("SELECT workspace_id FROM messages").fetchone()[0] == "w9"


@pytest.mark.sqlite_only
def test_0030_goes_down_and_up_again_without_losing_rows(tmp_path):
    path = tmp_path / "ave.db"
    Database(path)
    conn = migrate.connect(str(path))
    with_column = _cols(conn, "invoices")
    assert "workspace_id" in with_column
    while max(migrate.applied(conn)) >= 30:
        migrate.down(conn, 1)
    assert "workspace_id" not in _cols(conn, "invoices")
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name LIKE 'ws_default_%'").fetchone()
    migrate.up(conn)
    assert "workspace_id" in _cols(conn, "invoices")
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name = 'ws_default_invoices'").fetchone()


def test_no_schema_change_lives_outside_the_migrations():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        if "migrations" in path.parts or path.name == "migrate.py":
            continue
        text = path.read_text()
        for needle in ("ALTER TABLE", "CREATE TABLE", "CREATE INDEX", "CREATE TRIGGER", "DROP TABLE"):
            if needle in text:
                offenders.append(f"{path.relative_to(root)}: {needle}")
    assert offenders == []


def test_launch_flags_are_off_by_default_even_for_the_default_owners():
    flags = FlagStore(Database(), ("local",))
    assert not flags.enabled("launch.invite_only", "local")
    assert not flags.enabled("launch.invite_only")
    assert "launch.invite_only" not in flags.enabled_for("local")


def test_a_flag_set_for_everyone_holds_unless_an_owner_has_their_own_row():
    flags = FlagStore(Database(), ("local",))
    flags.set("launch.invite_only", ALL, True)
    assert flags.enabled("launch.invite_only", "google:ann") and flags.enabled("launch.invite_only")
    assert "launch.invite_only" in flags.enabled_for("google:ann")
    flags.set("launch.invite_only", "google:ann", False)
    assert not flags.enabled("launch.invite_only", "google:ann")
    assert flags.enabled("launch.invite_only", "google:bo")


def test_the_flags_cli_sets_a_flag_for_everyone(tmp_path, capsys):
    path = str(tmp_path / "ave.db")
    flags_main(["set", "launch.invite_only", "on", "--db", path])
    assert "launch.invite_only" in capsys.readouterr().out
    assert FlagStore(Database(path)).enabled("launch.invite_only", "google:anyone")
    flags_main(["clear", "launch.invite_only", "--db", path])
    assert not FlagStore(Database(path)).enabled("launch.invite_only", "google:anyone")


@pytest.mark.sqlite_only
def test_the_migrations_run_on_a_database_made_before_the_runner(tmp_path):
    """A pre-runner file (only 0001's shape, nothing recorded) comes up to date."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path, isolation_level=None)
    from app.store.migrations import m0001_baseline
    conn.execute("BEGIN")
    m0001_baseline.up(conn)
    conn.execute("COMMIT")
    conn.close()
    Database(path)
    conn = migrate.connect(str(path))
    assert [r["applied_at"] is not None for r in migrate.status(conn)] == [True] * len(migrate.status(conn))
