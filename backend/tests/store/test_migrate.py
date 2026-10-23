"""Step 0 (M0): the numbered migration runner. A fresh database gets every
step; a database made before the runner is recognised and marked applied
without a change; every step rolls back and forward again cleanly."""
import os
import shutil
import sqlite3

import pytest

from app.store import migrate
from app.store.db import Database
from app.store.migrations import all_migrations

# The schema exactly as db.py made it before the runner (2026-10-20).
PRE_RUNNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id                TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- JSON
    transcript        TEXT NOT NULL,   -- JSON
    consent_at        TEXT,
    candidate_counter INTEGER NOT NULL DEFAULT 0,
    speakers          TEXT NOT NULL DEFAULT '{}',  -- JSON: label -> {name, voice_id}
    settings          TEXT NOT NULL DEFAULT '{}',  -- JSON: per-video preferences
    project_id        TEXT                         -- the folder it is in (Folders), NULL = standalone
);
CREATE INDEX IF NOT EXISTS videos_by_owner ON videos (owner, created_at);
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,                  -- f<n>
    owner       TEXT NOT NULL,
    name        TEXT NOT NULL,
    brief       TEXT NOT NULL DEFAULT '',
    settings    TEXT NOT NULL DEFAULT '{}',        -- JSON: defaults for new videos
    ceiling_usd REAL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS projects_by_owner ON projects (owner, created_at);
CREATE TABLE IF NOT EXISTS candidates (
    project_id   TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    body         TEXT NOT NULL,        -- JSON
    PRIMARY KEY (project_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS edits (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- approval order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS messages (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    text       TEXT NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS turns (
    project_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- "user" | "assistant"
    content    TEXT NOT NULL,          -- JSON: the content blocks as the model saw them (Phase 20)
    at         TEXT NOT NULL,
    PRIMARY KEY (project_id, seq)
);
CREATE TABLE IF NOT EXISTS plans (
    project_id TEXT NOT NULL,
    plan_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,       -- creation order
    body       TEXT NOT NULL,          -- JSON
    PRIMARY KEY (project_id, plan_id)
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    vendor     TEXT NOT NULL,          -- "openai" | "elevenlabs" | "anthropic"
    what       TEXT NOT NULL,          -- e.g. "transcription", "speech", "intent"
    units      REAL NOT NULL,
    unit       TEXT NOT NULL,          -- "minutes" | "characters" | "tokens"
    usd        REAL NOT NULL,          -- estimated
    at         TEXT NOT NULL,
    folder_id  TEXT,                   -- the video's project at the time of the charge (Folders)
    turn_id    TEXT                    -- the turn that caused it (spend scopes); NULL outside a turn
);
CREATE INDEX IF NOT EXISTS usage_by_project ON usage (project_id);
CREATE TABLE IF NOT EXISTS jobs (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL UNIQUE,   -- J<seq>
    project_id TEXT NOT NULL,          -- the video
    turn_id    TEXT,
    kind       TEXT NOT NULL,          -- voice_line | design_voice | clone | mix | render_preview | export
    status     TEXT NOT NULL,          -- queued | running | done | failed | cancelled
    touched    REAL NOT NULL,          -- epoch seconds of the last change, for the timeout sweep
    body       TEXT NOT NULL           -- JSON: the whole record (2026-10-20, one processing model)
);
CREATE INDEX IF NOT EXISTS jobs_by_video ON jobs (project_id, seq);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (status);
"""
# ...and the columns its startup loop added to it.
PRE_RUNNER_COLUMNS = (("messages", "kind", "TEXT NOT NULL DEFAULT 'say'"), ("messages", "cost", "REAL"), ("messages", "data", "TEXT"))


# 0001 to 0006 describe the schema as it stood when the runner arrived.
TODAY = 6


def _conn(path=":memory:"):
    return migrate.connect(str(path))


def _shape(conn) -> dict:
    """Every table's columns (name, type, not null, default, pk) and every index, ignoring the runner's own table."""
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT IN ('sqlite_sequence', ?)", (migrate.TABLE,)):
        out[name] = sorted(tuple(r)[1:] for r in conn.execute(f"PRAGMA table_info({name})"))
    out["_indexes"] = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex%'"))
    return out


def _rows(conn) -> dict:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT IN ('sqlite_sequence', ?)", (migrate.TABLE,))]
    return {t: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {t}")) for t in tables}


# Numbers held for steps on other branches (0032 accounts, 0033 search index).
RESERVED = {32, 33, 38}


def test_versions_are_numbered_from_one_without_gaps():
    versions = [m.version for m in all_migrations()]
    assert versions == [v for v in range(1, versions[-1] + 1) if v not in RESERVED or v in versions]


def test_a_fresh_database_gets_every_step_and_records_it():
    conn = _conn()
    ran = migrate.up(conn)
    assert list(ran) == [m.version for m in all_migrations()]
    assert all(row["applied_at"] for row in migrate.status(conn))
    shape = _shape(conn)
    assert {"meta", "videos", "projects", "candidates", "edits", "messages", "turns", "plans", "usage", "jobs"} <= set(shape)
    assert {"speakers", "settings", "project_id"} <= {c[0] for c in shape["videos"]}
    assert {"kind", "cost", "data"} <= {c[0] for c in shape["messages"]}
    assert {"folder_id", "turn_id"} <= {c[0] for c in shape["usage"]}
    assert migrate.up(conn) == {}                                    # nothing left to do


def test_a_database_made_before_the_runner_is_recognised_and_left_as_it_was():
    conn = _conn()
    conn.executescript(PRE_RUNNER_SCHEMA)
    for table, column, definition in PRE_RUNNER_COLUMNS:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute("INSERT INTO meta VALUES ('times_v2', '2026-10-19T00:00:00.000Z')")
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript, speakers) VALUES ('p1', 'local', '2026-10-19T00:00:00.000Z', '{}', '{}', '{\"A\": {}}')")
    conn.execute("INSERT INTO messages (project_id, seq, role, text, at, kind, cost) VALUES ('p1', 1, 'assistant', 'hi', '2026-10-19T00:00:00.000Z', 'step', 0.01)")
    conn.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at, turn_id) VALUES ('p1', 'openai', 'transcription', 1, 'minutes', 0.006, '2026-10-19T00:00:00.000Z', 't1')")
    before_shape, before_rows = _shape(conn), _rows(conn)

    ran = migrate.up(conn, TODAY)                                    # the steps that are today's schema

    assert sorted(ran) == list(range(1, TODAY + 1))
    assert ran[1] is False and ran[6] == 0                           # no rename, no time rewritten
    after_shape = _shape(conn)
    for table, cols in before_shape.items():
        assert after_shape[table] == cols, table                     # the old schema, untouched
    after_rows = _rows(conn)
    for table, rows in before_rows.items():
        assert after_rows[table] == rows, table                      # and every row


@pytest.mark.parametrize("migration", all_migrations(), ids=lambda m: f"{m.version:04d}_{m.name}")
def test_each_step_goes_down_to_the_shape_before_it_and_up_again(migration):
    conn = _conn()
    # Count the steps before it (a reserved number not landed yet leaves a gap).
    migrate.up(conn, [m.version for m in all_migrations()].index(migration.version))
    before = _shape(conn)
    migrate.up(conn, 1)
    after = _shape(conn)
    assert max(migrate.applied(conn)) == migration.version

    assert migrate.down(conn, 1) == [migration.version]
    assert _shape(conn) == before
    assert migration.version not in migrate.applied(conn)

    migrate.up(conn, 1)
    assert _shape(conn) == after


def test_the_whole_ladder_goes_down_and_up_on_an_empty_database():
    conn = _conn()
    migrate.up(conn)
    full = _shape(conn)
    migrate.down(conn, len(all_migrations()))
    assert migrate.applied(conn) == {} and set(_shape(conn)) == {"_indexes"}
    migrate.up(conn)
    assert _shape(conn) == full


def test_the_baseline_never_drops_tables_that_hold_rows():
    conn = _conn()
    migrate.up(conn)
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript) VALUES ('p1', 'local', 'x', '{}', '{}')")
    migrate.down(conn, len(all_migrations()) - 1)
    with pytest.raises(RuntimeError, match="videos"):
        migrate.down(conn, 1)
    assert migrate.applied(conn) == {1: migrate.applied(conn)[1]}    # the failed step rolled back, still applied
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1


def test_a_failing_step_leaves_the_database_as_it_was(monkeypatch):
    conn = _conn()
    migrate.up(conn, 4)
    before = _shape(conn)
    step = next(m for m in all_migrations() if m.version == 5)

    def broken(c):
        step.up(c)
        raise RuntimeError("boom")
    monkeypatch.setattr(migrate, "all_migrations", lambda: [m if m.version != 5 else type(m)(5, m.name, broken, m.down) for m in all_migrations()])
    with pytest.raises(RuntimeError):
        migrate.up(conn)
    assert _shape(conn) == before and max(migrate.applied(conn)) == 4


@pytest.mark.sqlite_only
def test_the_database_runs_the_runner_at_startup(tmp_path):
    path = tmp_path / "ave.db"
    db = Database(path)
    assert db.migrated_projects_to_videos is False
    conn = _conn(path)
    assert set(migrate.applied(conn)) == {m.version for m in all_migrations()}
    conn.close()
    again = Database(path)
    assert again.migrated_times == 0


def test_the_command_line_applies_rolls_back_and_reports(tmp_path, capsys):
    path = str(tmp_path / "cli.db")
    last = all_migrations()[-1].version
    assert migrate.main(["up", "2", "--db", path]) == 0
    out = capsys.readouterr().out
    assert "applied 0001" in out and "applied 0002" in out and "pending" in out
    assert migrate.main(["up", "--db", path]) == 0
    assert migrate.main(["down", "--db", path]) == 0
    assert f"rolled back {last:04d}" in capsys.readouterr().out
    assert migrate.main(["status", "--db", path]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == len(all_migrations()) and lines[-1].endswith("pending")


@pytest.mark.skipif(not os.environ.get("AVE_LIVE_DB_COPY"), reason="set AVE_LIVE_DB_COPY to a copy of a real database")
def test_a_copy_of_a_real_database_survives_up_down_up(tmp_path):
    path = tmp_path / "copy.db"
    shutil.copy(os.environ["AVE_LIVE_DB_COPY"], path)
    conn = _conn(path)
    before = _shape(conn)

    def original_rows():
        # Every original table's rows over its original columns (meta holds the runner's markers).
        return {t: sorted(repr(tuple(r)) for r in conn.execute(f"SELECT {', '.join(c[0] for c in cols)} FROM {t}"))
                for t, cols in before.items() if t not in ("_indexes", "meta")}
    rows = original_rows()
    migrate.up(conn)
    assert original_rows() == rows
    full = _shape(conn)
    migrate.down(conn, len(all_migrations()) - TODAY)                # every step after today's schema
    assert _shape(conn) == before and original_rows() == rows
    migrate.up(conn)
    assert _shape(conn) == full and original_rows() == rows
