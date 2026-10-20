"""F8: soft delete and the purge. A deleted video or project is hidden from
every list and get; the purge removes rows and stored media of what has
been in the Bin long enough, never the charges, which keep the item's name."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.purge import main as purge_cli, purge
from app.store import migrate
from app.store.db import Database
from app.store.repository import ProjectRepository
from app.usage import Ledger
from tests.factories import make_source
from tests.store.test_repository import TRANSCRIPT, make_edit

LATER = datetime.now(timezone.utc) + timedelta(days=31)


@pytest.fixture()
def world(tmp_path):
    db = Database(tmp_path / "ave.db")
    repo, ledger = ProjectRepository(db), Ledger(db)
    repo.create_project("local", "Spring", brief="Bright.")
    repo.create(make_source(project_id="p1", filename="ad.mp4"), TRANSCRIPT, folder_id="f1")
    repo.create(make_source(project_id="p2", filename="keep.mp4"), TRANSCRIPT)
    repo.append_edit("p1", make_edit("e1"))
    repo.set_settings("p1", made_voices=[{"voice_id": "MADE1", "name": "Dusk"}])
    ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.25)
    ledger.record_project_level("f1", "elevenlabs", "design", 1, "calls", 0.1)
    root = tmp_path / "artifacts"
    for key in ("p1", "p2", "projects/f1/files", "user-local"):
        (root / key).mkdir(parents=True)
    (root / "p1" / "abc.wav").write_bytes(b"x")
    (root / "projects" / "f1" / "files" / "def").write_bytes(b"x")
    (root / "user-local" / "s1.wav").write_bytes(b"x")
    repo.set_meta("my_voices:local", json.dumps([
        {"voice_id": "V1", "name": "Mine", "sample_sha": "s1", "deleted_at": "2026-01-01T00:00:00.000Z", "deleted_by": "local"},
        {"voice_id": "V2", "name": "Kept", "sample_sha": None}]))
    return repo, ledger, root


def test_deleted_videos_and_projects_are_hidden_from_every_list_and_get(world):
    repo, _, _ = world
    assert repo.soft_delete("p1", "local") and not repo.soft_delete("p1", "local")
    assert repo.get("p1") is None and repo.get("p1", include_deleted=True).source.project_id == "p1"
    assert [r.source.project_id for r in repo.list("local")] == ["p2"]
    assert [r.source.project_id for r in repo.list("local", folder="f1")] == []
    assert len(repo.list("local", include_deleted=True)) == 2
    assert repo.soft_delete_project("f1", "local", keep_videos=False)
    assert repo.get_project("f1") is None and repo.list_projects("local") == []
    assert repo.get_project("f1", include_deleted=True).name == "Spring"


def test_deleting_a_project_keeping_its_videos_makes_them_standalone(world):
    repo, _, _ = world
    repo.soft_delete_project("f1", "local", keep_videos=True)
    assert repo.get("p1").folder_id is None


def test_the_purge_removes_rows_and_storage_and_keeps_the_charges_by_name(world):
    repo, ledger, root = world
    repo.soft_delete_project("f1", "local", keep_videos=False)
    before = ledger.spent_usd_by_owner("local")
    assert before == pytest.approx(0.35)

    soon = purge(repo.db, root, 30)                                   # nothing has been in the Bin 30 days
    assert soon.videos == [] and soon.projects == [] and soon.voices == ["local:V1"]

    dry = purge(repo.db, root, 30, dry_run=True, now=LATER)
    assert (dry.videos, dry.projects) == (["p1"], ["f1"]) and (root / "p1").exists()
    assert repo.get("p1", include_deleted=True) is not None

    deleted: list[str] = []
    done = purge(repo.db, root, 30, delete_voice=deleted.append, now=LATER)
    assert (done.videos, done.projects) == (["p1"], ["f1"])
    assert not (root / "p1").exists() and not (root / "projects" / "f1").exists() and (root / "p2").exists()
    assert repo.get("p1", include_deleted=True) is None and repo.get_project("f1", include_deleted=True) is None
    assert repo.list_edits("p1") == []
    assert deleted == ["MADE1"] and done.vendor_voices == ["MADE1"]
    # Charges are never deleted, still count against the owner, and keep their names.
    assert ledger.spent_usd_by_owner("local") == pytest.approx(before)
    with repo.db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 2
        names = {(r["kind"], r["item_id"]): r["name"] for r in c.execute("SELECT * FROM purged_items")}
        assert c.execute("SELECT COUNT(*) FROM project_events WHERE project_id = 'f1' OR video_id = 'p1'").fetchone()[0] == 0
    assert names[("video", "p1")] == "ad.mp4" and names[("project", "f1")] == "Spring"


def test_a_voice_in_the_bin_is_purged_with_its_sample_and_at_the_vendor(world):
    repo, _, root = world
    deleted: list[str] = []
    done = purge(repo.db, root, 30, delete_voice=deleted.append)
    assert done.voices == ["local:V1"] and "V1" in deleted
    assert not (root / "user-local" / "s1.wav").exists()
    assert [v["voice_id"] for v in json.loads(repo.get_meta("my_voices:local"))] == ["V2"]


def test_a_vendor_failure_is_reported_and_never_stops_the_purge(world):
    repo, _, root = world
    repo.soft_delete("p1", "local")

    def refuse(voice_id):
        raise RuntimeError("vendor down")
    done = purge(repo.db, root, 30, delete_voice=refuse, now=LATER)
    assert done.videos == ["p1"] and sorted(done.vendor_failed) == ["MADE1", "V1"] and done.vendor_voices == []


def test_a_voice_another_video_still_holds_stays_at_the_vendor(world):
    repo, _, root = world
    repo.set_settings("p2", made_voices=[{"voice_id": "MADE1", "name": "Dusk"}])
    repo.soft_delete("p1", "local")
    deleted: list[str] = []
    purge(repo.db, root, 30, delete_voice=deleted.append, now=LATER)
    assert "MADE1" not in deleted


def test_the_command_line_dry_run_changes_nothing(world, tmp_path, capsys):
    repo, _, _ = world
    repo.soft_delete("p1", "local")
    assert purge_cli(["--days", "0", "--dry-run", "--db", str(tmp_path / "ave.db"), "--data-dir", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["videos"] == ["p1"] and "MADE1" in out["vendor_voices"]
    assert repo.get("p1", include_deleted=True) is not None and (tmp_path / "artifacts" / "p1").exists()


def test_0013_goes_down_and_up_and_refuses_while_something_is_in_the_bin():
    conn = migrate.connect(":memory:")
    migrate.up(conn, 12)
    conn.execute("INSERT INTO videos (id, owner, created_at, source, transcript) VALUES ('p1', 'local', 'x', '{}', '{}')")
    assert list(migrate.up(conn, 1)) == [13]
    conn.execute("UPDATE videos SET deleted_at = 'T'")
    with pytest.raises(RuntimeError, match="come back as live"):
        migrate.down(conn, 1)
    conn.execute("UPDATE videos SET deleted_at = NULL")
    assert migrate.down(conn, 1) == [13]
    assert "deleted_at" not in {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    migrate.up(conn, 1)


def test_the_command_line_purges_with_the_app_s_voice_vendor(world, tmp_path, capsys):
    repo, _, _ = world
    repo.soft_delete("p1", "local")
    assert purge_cli(["--days", "-1", "--db", str(tmp_path / "ave.db"), "--data-dir", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["videos"] == ["p1"] and out["vendor_failed"] == [] and "MADE1" in out["vendor_voices"]  # the mock's delete
    assert not (tmp_path / "artifacts" / "p1").exists()
