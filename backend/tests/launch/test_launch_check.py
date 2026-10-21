"""Launch item 11: the pieces of `make launch-check`."""
from app.store.db import Database
from app.store.repository import ProjectRepository
from app.domain.models import Transcript
from app.tools import env_check, migration_check
from tests.factories import make_source


import pytest


@pytest.mark.sqlite_only
def test_the_migration_check_round_trips_a_copy_and_leaves_the_original(tmp_path):
    path = tmp_path / "ave.db"
    repo = ProjectRepository(Database(path))
    repo.create(make_source(project_id="p1"), Transcript(words=()))
    before = path.read_bytes()
    assert migration_check.check(path, 29) == []
    assert migration_check.main(["--db", str(path)]) == 0
    assert path.read_bytes() == before
    assert migration_check.main(["--db", str(tmp_path / "missing.db")]) == 1


def test_the_env_check_reads_a_file_and_names_what_is_missing(tmp_path, monkeypatch, capsys):
    for name in ("AVE_SESSION_SECRET", "AVE_SHARE_SECRET", "AVE_PUBLIC_URL", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY",
                 "OPENAI_API_KEY", "AVE_EMAIL_PROVIDER", "AVE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env.production"
    env.write_text("AVE_SESSION_SECRET=" + "s" * 40 + "\nAVE_SHARE_SECRET='" + "k" * 40 + "'\nAVE_PUBLIC_URL=https://voltage.example\n"
                   "ANTHROPIC_API_KEY=a\nELEVENLABS_API_KEY=e\nAVE_EMAIL_PROVIDER=resend\nAVE_AUTH=accounts\n")
    assert env_check.main(["--env-file", str(env)]) == 1
    assert "OPENAI_API_KEY is missing" in capsys.readouterr().out
    env.write_text(env.read_text() + "OPENAI_API_KEY=o\n")
    assert env_check.main(["--env-file", str(env)]) == 0
