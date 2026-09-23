import os

import pytest

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


# --- ElevenLabs, budget, dry-run (Phase 4a) ---------------------------------

def test_settings_report_no_elevenlabs_when_the_key_is_blank(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    assert config.load_settings().has_elevenlabs is False


def test_settings_report_elevenlabs_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_something")
    settings = config.load_settings()
    assert settings.has_elevenlabs is True
    assert settings.elevenlabs_api_key == "sk_something"


def test_elevenlabs_model_and_voice_have_spike_chosen_defaults(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_MODEL", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    settings = config.load_settings()
    assert settings.elevenlabs_model == "eleven_multilingual_v2"
    assert settings.elevenlabs_voice_id == "EXAVITQu4vr4xnSDxMaL"  # Sarah, premade


def test_elevenlabs_model_and_voice_can_be_overridden(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v123")
    settings = config.load_settings()
    assert settings.elevenlabs_model == "eleven_flash_v2_5"
    assert settings.elevenlabs_voice_id == "v123"


def test_voice_budget_defaults_to_2000_characters(monkeypatch):
    monkeypatch.delenv("AVE_VOICE_BUDGET_CHARS", raising=False)
    assert config.load_settings().voice_budget_chars == 2000


def test_voice_budget_parses_an_integer(monkeypatch):
    monkeypatch.setenv("AVE_VOICE_BUDGET_CHARS", "50")
    assert config.load_settings().voice_budget_chars == 50


@pytest.mark.parametrize("bad", ["-1", "lots", "1.5"])
def test_voice_budget_rejects_nonsense(monkeypatch, bad):
    monkeypatch.setenv("AVE_VOICE_BUDGET_CHARS", bad)
    with pytest.raises(ValueError, match="AVE_VOICE_BUDGET_CHARS"):
        config.load_settings()


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("YES", True),
    ("0", False), ("false", False), ("", False),
])
def test_dry_run_flag(monkeypatch, value, expected):
    monkeypatch.setenv("AVE_DRY_RUN", value)
    assert config.load_settings().dry_run is expected


def test_dry_run_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AVE_DRY_RUN", raising=False)
    assert config.load_settings().dry_run is False
