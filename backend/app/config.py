"""Runtime configuration, including vendor credentials.

Secrets come from the environment, optionally seeded from a git-ignored
`backend/.env`. Real environment variables always win, so a deployment or CI
can override the file without editing it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_ROOT / ".env"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Seed os.environ from a KEY=VALUE file. Existing values are left alone."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    data_dir: Path

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        data_dir=Path(os.environ.get("AVE_DATA_DIR", BACKEND_ROOT / "var")),
    )
