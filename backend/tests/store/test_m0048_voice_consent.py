"""Voice consent V1, step 1: migration 0048 gives every existing voice a scope
per the plan's table, adds the five tables, loses nothing, and its down puts
the database back as it was. The dry run reports the same counts on a copy
and never changes the original."""
import json
import sqlite3

import pytest

from app.store import migrate
from app.store.migrations import all_migrations, m0048_voice_consent as m0048
from app.tools import voice_scope_dry_run

NOW = "2026-10-30T10:00:00.000Z"


def _before_0048(path=":memory:"):
    conn = migrate.connect(str(path))
    migrate.up(conn, sum(1 for m in all_migrations() if m.version < 48))
    return conn


def _video(conn, vid, *, speakers=None, settings=None, deleted=False, owner="u1"):
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript, speakers, settings, deleted_at) "
                 "VALUES (?, ?, ?, '{}', '{}', ?, ?, ?)",
                 (vid, owner, NOW, json.dumps(speakers or {}), json.dumps(settings or {}), NOW if deleted else None))


def _check(conn, attempt, vid, speaker=None, method="verified", status="passed", owner="u1"):
    conn.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, created_at) "
                 "VALUES (?, ?, ?, ?, 'a phrase', ?, 'verified', ?, ?)", (attempt, owner, vid, speaker, status, method, NOW))


def _seed(conn):
    conn.execute("INSERT INTO workspaces (id, name, owner, created_at) VALUES ('w1', 'Mine', 'u1', ?)", (NOW,))
    conn.execute("INSERT INTO projects (id, owner, name, created_at) VALUES ('f1', 'u1', 'Diwali', ?)", (NOW,))
    # p1: a clone whose check passed (the real gate); p2: a clone with only the stand-in check;
    # p3: a clone in the Bin; p4: a designed voice made inside it.
    _video(conn, "p1", speakers={"A": {"name": "Asha", "clone_voice_id": "v-verified"}})
    _check(conn, "cv_1", "p1", speaker="A")
    _video(conn, "p2", speakers={"A": {"name": "Speaker A", "clone_voice_id": "v-video"}})
    _check(conn, "lv_1", "p2", method="")
    _video(conn, "p3", speakers={"_": {"clone_voice_id": "v-binned"}}, deleted=True)
    _video(conn, "p4", settings={"made_voices": [{"voice_id": "v-designed", "kind": "designed"},
                                                 {"voice_id": "v-library", "kind": "library"}]})
    mine = [{"voice_id": "v-upload", "name": "Me", "kind": "recorded"},
            # kept from a video that was purged since: no row for p9 any more
            {"voice_id": "v-gone", "name": "Old", "kind": "cloned", "source": {"video_id": "p9", "label": "B"}},
            {"voice_id": "v-designed-mine", "name": "Calm", "kind": "designed"}]
    conn.execute("INSERT INTO meta (key, value) VALUES ('my_voices:u1', ?)", (json.dumps(mine),))
    conn.execute("INSERT INTO meta (key, value) VALUES ('project_voices:f1', ?)", (json.dumps([mine[0]]),))   # shared: same voice


EXPECTED = {"designed_or_stock": 3, "clone_verified": 1, "clone_video": 2, "clone_source_deleted": 1, "upload": 1,
            "clone_video_in_bin": 1}


def _records(conn):
    return {r[0]: dict(zip(("voice_id", "scope", "status", "source_video_id", "speaker_label", "verified_consent_id",
                            "vendor_state", "migration_row", "workspace_id", "kind"), r))
            for r in conn.execute("SELECT voice_id, scope, status, source_video_id, speaker_label, verified_consent_id, "
                                  "vendor_state, migration_row, workspace_id, kind FROM voice_records")}


def _everything(conn):
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                                        "AND name != 'schema_migrations' AND name NOT LIKE 'search_fts%'")]
    return {n: sorted(map(tuple, conn.execute(f"SELECT * FROM {n}"))) for n in names}


def test_every_existing_voice_gets_its_row_of_the_plans_table():
    conn = _before_0048()
    _seed(conn)
    written = migrate._run(conn, next(m for m in all_migrations() if m.version == 48), "up")
    assert written == EXPECTED
    got = _records(conn)
    assert set(got) == {"v-verified", "v-video", "v-binned", "v-designed", "v-library", "v-upload", "v-gone", "v-designed-mine"}
    assert (got["v-verified"]["scope"], got["v-verified"]["status"], got["v-verified"]["verified_consent_id"]) == \
        ("library", "active", "cv_1")
    assert (got["v-video"]["scope"], got["v-video"]["source_video_id"], got["v-video"]["speaker_label"]) == ("video", "p2", "A")
    assert got["v-video"]["verified_consent_id"] is None                     # the stand-in check does not count
    assert (got["v-binned"]["scope"], got["v-binned"]["status"], got["v-binned"]["vendor_state"]) == ("video", "active", "live")
    assert (got["v-gone"]["status"], got["v-gone"]["vendor_state"], got["v-gone"]["migration_row"]) == \
        ("withdrawn", "delete_queued", "clone_source_deleted")               # queued, never called here
    for vid in ("v-designed", "v-library", "v-designed-mine", "v-upload"):
        assert got[vid]["scope"] == "library" and got[vid]["status"] == "active"
    assert {r["workspace_id"] for r in got.values()} == {"w1"}
    for table in ("voice_attestations", "export_attestations", "line_checks", "synthesis_log", "no_go_voices"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_nothing_is_lost_and_down_restores_the_database():
    conn = _before_0048()
    _seed(conn)
    before = _everything(conn)
    step = next(m for m in all_migrations() if m.version == 48)
    migrate._run(conn, step, "up")
    after = _everything(conn)
    assert {t: rows for t, rows in after.items() if t in before} == before   # only added to
    assert migrate._run(conn, step, "up") is None                            # applied once
    assert m0048.up(conn) == EXPECTED and len(_records(conn)) == 8           # idempotent: no second row
    migrate._run(conn, step, "down")
    assert _everything(conn) == before


def test_down_refuses_while_it_holds_evidence():
    conn = _before_0048()
    _seed(conn)
    step = next(m for m in all_migrations() if m.version == 48)
    migrate._run(conn, step, "up")
    conn.execute("INSERT INTO voice_attestations (id, owner, video_id, choice, statement_version, created_at) "
                 "VALUES ('va_1', 'u1', 'p2', 'my_voice', '1', ?)", (NOW,))
    with pytest.raises(RuntimeError, match="voice_attestations holds 1"):
        migrate._run(conn, step, "down")
    conn.execute("DELETE FROM voice_attestations")
    conn.execute("UPDATE voice_records SET status = 'withdrawn', updated_at = 'later' WHERE voice_id = 'v-video'")
    with pytest.raises(RuntimeError, match="made or changed since the migration"):
        migrate._run(conn, step, "down")


def test_the_dry_run_counts_on_a_copy_and_leaves_the_original(tmp_path, capsys):
    path = tmp_path / "ave.db"
    conn = _before_0048(path)
    _seed(conn)
    conn.close()
    original = path.read_bytes()
    report = voice_scope_dry_run.run(path)
    assert report["problems"] == [] and report["counts"] == EXPECTED and len(report["voices"]) == 8
    assert voice_scope_dry_run.main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "1  Clone whose source video is deleted" in out and "down restores the copy" in out
    assert path.read_bytes() == original                                     # the original never changes
    with sqlite3.connect(path) as c:
        assert 48 not in {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
