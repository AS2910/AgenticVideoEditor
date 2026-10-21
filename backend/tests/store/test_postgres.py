"""Postgres behind the store (launch, item 6).

The rewriting tests run everywhere. The rest need a server: set
AVE_TEST_DATABASE_URL (the conftest then gives this session its own database).
"""
import os
from urllib.parse import quote

import pytest

from app.store import migrate, pg
from app.store.db import Database
from app.store.migrations import all_migrations

ON_PG = bool(os.environ.get(pg.TEST_URL_ENV))
needs_pg = pytest.mark.skipif(not ON_PG, reason="needs AVE_TEST_DATABASE_URL (a Postgres server)")


def _sql(sql, params=True, **kw):
    return pg.rewrite(sql, has_params=params, **kw).sql


def test_placeholders_and_percent_signs_but_not_inside_strings():
    out = _sql("SELECT ? FROM meta WHERE key LIKE 'a:%' AND value = 'why?' AND x = ?")
    assert out == "SELECT %s FROM meta WHERE key LIKE 'a:%%' AND value = 'why?' AND x = %s"
    assert _sql("SELECT 1 FROM meta WHERE key LIKE 'a:%'", params=False) == "SELECT 1 FROM meta WHERE key LIKE 'a:%'"


def test_comments_go_and_their_quotes_do_not_open_a_string():
    out = _sql("CREATE TABLE t (\n    a TEXT, -- the owner's ?\n    b INTEGER\n)", params=False)
    assert "owner" not in out and "b BIGINT" in out and "rowid BIGSERIAL" in out


def test_autoincrement_keys_become_sequences_and_the_rowid():
    out = _sql("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, usd REAL NOT NULL)", params=False)
    assert "id BIGSERIAL PRIMARY KEY" in out
    assert "usd DOUBLE PRECISION NOT NULL" in out
    assert "rowid BIGINT GENERATED ALWAYS AS (id) STORED" in out


def test_inserts_return_the_rowid_and_or_ignore_does_nothing_on_conflict():
    r = pg.rewrite("INSERT OR IGNORE INTO pins (a, b) VALUES (?, ?)", has_params=True)
    assert r.sql == "INSERT INTO pins (a, b) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING rowid"
    assert r.returning_rowid
    own = pg.rewrite("INSERT INTO t (a) VALUES (?) RETURNING id", has_params=True)
    assert own.sql.endswith("RETURNING id") and not own.returning_rowid


def test_or_replace_is_an_upsert_on_the_primary_key():
    out = _sql("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
               conflict_keys=lambda table: (["key"], True))
    assert out == ("INSERT INTO meta (key, value) VALUES (%s, %s) "
                   "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, rowid = DEFAULT RETURNING rowid")


def test_pragma_sqlite_master_begin_and_last_insert_rowid():
    assert "information_schema.columns" in _sql("PRAGMA table_info(usage)", params=False)
    assert pg.rewrite("PRAGMA busy_timeout=5000", has_params=False).skip
    assert "information_schema.tables" in _sql("SELECT name FROM sqlite_master WHERE type = 'table'", params=False)
    assert _sql("BEGIN IMMEDIATE", params=False) == "BEGIN"
    assert _sql("SELECT * FROM t WHERE id = last_insert_rowid()", params=False, last_rowid=7) == "SELECT * FROM t WHERE id = 7"


def test_sqlite_stays_sqlite_without_a_url(monkeypatch):
    monkeypatch.delenv(pg.TEST_URL_ENV, raising=False)
    assert pg.target(":memory:") is None
    assert pg.target("var/ave.db") is None
    assert pg.target("postgres://u@h/db") == ("postgres://u@h/db", None, False)
    assert Database().dialect == "sqlite"


# ------------------------------------------------------------ on a server

@needs_pg
def test_rows_read_by_name_and_position_and_ids_come_back():
    db = Database()
    assert db.dialect == "postgres"
    with db.tx() as c:
        cur = c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ("v1", "openai", "speech", 2, "minutes", 0.25, "2026-01-01T00:00:00.000Z"))
        first = cur.lastrowid
        c.execute("INSERT INTO usage (project_id, vendor, what, units, unit, usd, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  ("v1", "openai", "speech", 1, "minutes", 0.5, "2026-01-01T00:00:01.000Z"))
        last = c.execute("SELECT * FROM usage WHERE id = last_insert_rowid()").fetchone()
        total = c.execute("SELECT SUM(LENGTH(vendor)) AS n, SUM(usd) AS usd FROM usage").fetchone()
    assert last["id"] == first + 1 and last[0] == first + 1 and "rowid" not in last.keys()  # noqa: SIM118 (keys() is what is tested)
    assert dict(last)["usd"] == 0.5
    assert total["N"] == 12 and isinstance(total["n"], int) and total["usd"] == 0.75


@needs_pg
def test_or_replace_and_or_ignore_behave_as_on_sqlite():
    db = Database()
    with db.tx() as c:
        for value in ("a", "b"):
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("k", value))
        assert c.execute("SELECT value FROM meta WHERE key = ?", ("k",)).fetchone()[0] == "b"
        args = ("o", "video", "v1", "2026-01-01T00:00:00.000Z", None)
        sql = "INSERT OR IGNORE INTO pins (owner, kind, item_id, pinned_at, workspace_id) VALUES (?, ?, ?, ?, ?)"
        assert c.execute(sql, args).rowcount == 1
        assert c.execute(sql, args).rowcount == 0


@needs_pg
def test_rls_hides_another_workspaces_rows_once_bypass_is_off():
    db = Database()
    with db.tx() as c:
        for ws, owner in (("w1", "alice"), ("w2", "bob")):
            c.execute("INSERT INTO workspaces (id, name, owner, created_at) VALUES (?, ?, ?, ?)", (ws, "W", owner, "2026-01-01"))
            c.execute("INSERT INTO videos (id, owner, created_at, source, transcript, workspace_id) VALUES (?, ?, ?, ?, ?, ?)",
                      (f"v-{owner}", owner, "2026-01-01", "{}", "[]", ws))
    raw = db._conn.raw
    raw.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ave_rls_test') "
                "THEN CREATE ROLE ave_rls_test NOLOGIN; END IF; END $$")
    raw.execute(f'GRANT USAGE ON SCHEMA "{db._conn.schema}" TO ave_rls_test')
    raw.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{db._conn.schema}" TO ave_rls_test')
    try:
        with db.tx() as c:
            c.execute("SET LOCAL ROLE ave_rls_test")
            assert c.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2   # bypass on: the app as today
            c.execute("SELECT set_config('app.bypass_rls', 'off', true)")
            c.execute("SELECT set_config('app.workspace_id', 'w1', true)")
            assert [r[0] for r in c.execute("SELECT id FROM videos ORDER BY id")] == ["v-alice"]
            c.execute("SELECT set_config('app.workspace_id', 'w3', true)")
            assert c.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    finally:
        raw.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{db._conn.schema}" FROM ave_rls_test')
        raw.execute(f'REVOKE USAGE ON SCHEMA "{db._conn.schema}" FROM ave_rls_test')
    with db.tx() as c:   # the transaction ended: back to the app's own role, bypass on
        assert c.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2


@needs_pg
def test_every_workspace_table_has_the_policy():
    db = Database()
    with db.tx() as c:
        scoped = {r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND column_name = 'workspace_id'")}
        policed = {r[0] for r in c.execute(
            "SELECT tablename FROM pg_policies WHERE schemaname = current_schema() AND policyname = 'ws_scope'")}
    assert scoped and scoped == policed


@needs_pg
def test_the_cli_runs_against_a_postgres_url(capsys):
    from psycopg.conninfo import conninfo_to_dict
    info = conninfo_to_dict(os.environ[pg.TEST_URL_ENV])
    url = f"postgresql://{quote(info.get('user') or 'postgres')}@/{info['dbname']}?host={quote(info.get('host', ''), safe='')}"
    assert migrate.main(["up", "--db", url]) == 0
    assert migrate.main(["down", "2", "--db", url]) == 0
    assert migrate.main(["up", "--db", url]) == 0
    out = capsys.readouterr().out
    assert "rolled back" in out and "pending" not in out.splitlines()[-1]
    conn = migrate.connect(url)
    try:
        assert set(migrate.applied(conn)) == {m.version for m in all_migrations()}
    finally:
        conn.close()
