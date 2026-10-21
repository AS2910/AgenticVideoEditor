"""Launch item 4: the backup script and a tested restore (OPS.md)."""
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.store.db import Database
from app.store.repository import ProjectRepository
from tests.factories import make_source
from app.domain.models import Transcript

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(not shutil.which("sqlite3") or not shutil.which("shasum"), reason="sqlite3/shasum not installed")


def _counts(path: Path) -> dict:
    c = sqlite3.connect(path)
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {n: c.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}


def test_a_backup_restores_to_the_same_data(tmp_path):
    data = tmp_path / "var"
    db = Database(data / "ave.db")
    repo = ProjectRepository(db)
    repo.create(make_source(project_id="p1"), Transcript(words=()))
    repo.add_message("p1", "user", "Make it warmer")
    (data / "artifacts" / "p1").mkdir(parents=True)
    (data / "artifacts" / "p1" / "take.wav").write_bytes(b"RIFF....WAVE" * 100)
    before = _counts(data / "ave.db")

    out = subprocess.run([str(ROOT / "scripts/backup.sh"), str(data), str(tmp_path / "backups")],
                         check=True, capture_output=True, text=True)
    folder = Path(out.stdout.strip().splitlines()[-1])
    assert (folder / "ave.db").exists() and (folder / "data.tar.gz").exists() and (folder / "SHA256SUMS").exists()

    fresh = tmp_path / "restored"
    subprocess.run([str(ROOT / "scripts/restore.sh"), str(folder), str(fresh)], check=True, capture_output=True, text=True)
    assert _counts(fresh / "ave.db") == before
    assert (fresh / "artifacts" / "p1" / "take.wav").read_bytes() == b"RIFF....WAVE" * 100
    assert ProjectRepository(Database(fresh / "ave.db")).get("p1") is not None

    # It never writes over a live data dir without --force, and refuses a tampered backup.
    again = subprocess.run([str(ROOT / "scripts/restore.sh"), str(folder), str(fresh)], capture_output=True, text=True)
    assert again.returncode != 0 and "already has a database" in again.stderr
    (folder / "data.tar.gz").write_bytes(b"tampered")
    bad = subprocess.run([str(ROOT / "scripts/restore.sh"), str(folder), str(tmp_path / "other")], capture_output=True, text=True)
    assert bad.returncode != 0 and "does not match its checksums" in bad.stderr
