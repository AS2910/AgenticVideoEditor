"""D3: the Bin service (days left, restore rules), migration 0020 (the
consent record outlives the purge) and the opt-in daily purge."""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.config import load_settings
from app.purge import PurgeScheduler, consent_records, purge
from app.store import bin as bin_store, migrate
from app.store.db import Database
from app.store.repository import ProjectRepository
from app.domain.models import Consent
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def test_days_left_counts_down_from_30():
    assert bin_store.days_left("2026-10-21T11:00:00.000Z", NOW) == 30
    assert bin_store.days_left("2026-10-11T11:00:00.000Z", NOW) == 20
    assert bin_store.days_left("2026-09-01T00:00:00.000Z", NOW) == 0


@pytest.fixture()
def repo(tmp_path):
    repo = ProjectRepository(Database(tmp_path / "ave.db"))
    repo.create_project("local", "Spring")
    repo.create(make_source(project_id="p1", filename="ad.mp4"), TRANSCRIPT, Consent("2026-10-01T00:00:00.000Z"),
                folder_id="f1")
    return repo


def test_restore_rules_and_events(repo):
    repo.soft_delete_project("f1", "local", keep_videos=False)
    items = bin_store.items(repo.db, "local")
    assert [(i["kind"], i["id"]) for i in items] == [("video", "p1"), ("project", "f1")]
    assert bin_store.items(repo.db, "someone") == []
    with pytest.raises(bin_store.NotInBin):
        bin_store.restore_project(repo.db, "someone", "f1", "someone")
    assert bin_store.restore_project(repo.db, "local", "f1", "local") == {"videos": ["p1"]}
    assert repo.get("p1").folder_id == "f1" and repo.get_project("f1") is not None
    with repo.db.tx() as c:
        verbs = [r[0] for r in c.execute("SELECT verb FROM project_events ORDER BY id")]
    assert verbs[-2:] == ["video.restored", "project.restored"]


def test_the_purge_keeps_the_consent_record(repo, tmp_path):
    repo.set_meta("my_voices:local", json.dumps([
        {"voice_id": "V1", "name": "Mine", "consent_granted_at": "2026-09-01T00:00:00.000Z", "consent_approximate": True,
         "deleted_at": "2026-09-02T00:00:00.000Z", "deleted_by": "local"},
        {"voice_id": "V2", "name": "Designed", "deleted_at": "2026-09-02T00:00:00.000Z"}]))
    repo.soft_delete("p1", "local")
    report = purge(repo.db, tmp_path / "artifacts", 30, now=NOW + timedelta(days=31))
    assert sorted(report.consent_kept) == ["video:p1", "voice:local:V1"]
    kept = {r["item_id"]: r["consent"] for r in consent_records(repo.db, "local")}
    assert kept == {"p1": {"granted_at": "2026-10-01T00:00:00.000Z"},
                    "local:V1": {"granted_at": "2026-09-01T00:00:00.000Z", "approximate": True}}


def test_migration_0020_up_down_and_refuses_to_lose_a_consent_record(tmp_path):
    conn = migrate.connect(str(tmp_path / "m.db"))
    migrate.up(conn)
    migrate.down_to(conn, 20)   # 0020 is the last step applied
    cols = lambda: {r[1] for r in conn.execute("PRAGMA table_info(purged_items)")}
    assert "consent" in cols()
    conn.execute("INSERT INTO purged_items (kind, item_id, name, owner, purged_at, consent) "
                 "VALUES ('voice', 'local:V1', 'Mine', 'local', 'x', '{\"granted_at\": \"y\"}')")
    conn.commit()
    with pytest.raises(RuntimeError):
        migrate.down(conn, 1)
    conn.execute("UPDATE purged_items SET consent = NULL")
    conn.commit()
    migrate.down(conn, 1)
    assert "consent" not in cols() and "name" in cols()
    migrate.up(conn)
    assert "consent" in cols()


def test_the_daily_purge_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("AVE_PURGE_DAILY", raising=False)
    assert load_settings().purge_daily is False
    monkeypatch.setenv("AVE_PURGE_DAILY", "1")
    assert load_settings().purge_daily is True


def test_the_scheduler_runs_on_its_interval_and_survives_a_failure():
    ran = threading.Event()
    calls = []

    def run():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first one fails")
        ran.set()
    scheduler = PurgeScheduler(run, every=0.01)
    scheduler.start()
    assert ran.wait(2)
    scheduler.stop()
    assert len(calls) >= 2
