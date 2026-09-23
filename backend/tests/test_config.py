import os

from app import config


def test_dotenv_seeds_missing_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-file\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config.load_dotenv(env)
    assert os.environ["OPENAI_API_KEY"] == "from-file"


def test_the_real_environment_wins_over_the_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-environment")

    config.load_dotenv(env)
    assert os.environ["OPENAI_API_KEY"] == "from-environment"


def test_comments_blanks_and_quotes_are_handled(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nA_KEY="quoted"\nB_KEY=plain\nNOT_A_PAIR\n')
    for name in ("A_KEY", "B_KEY"):
        monkeypatch.delenv(name, raising=False)

    config.load_dotenv(env)
    assert os.environ["A_KEY"] == "quoted"
    assert os.environ["B_KEY"] == "plain"


def test_a_missing_file_is_not_an_error(tmp_path):
    config.load_dotenv(tmp_path / "nope.env")  # must not raise


def test_settings_report_no_openai_when_the_key_is_blank(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert config.load_settings().has_openai is False


def test_settings_report_openai_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-something")
    settings = config.load_settings()
    assert settings.has_openai is True
    assert settings.openai_api_key == "sk-something"
