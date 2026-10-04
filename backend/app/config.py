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


# Chosen by the Phase 4a spike (2026-09-23): multilingual_v2 accepts the
# previous_text/next_text context that conditions prosody (eleven_v3 refuses
# it), and Sarah is the premade voice closest to the sample clip's speaker.
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_VOICE_BUDGET_CHARS = 2000
# Extra paid takes allowed when a take fails continuity (spec §6 auto-retry).
DEFAULT_MAX_REGENERATIONS = 2
# Per-project ceiling on estimated spend across every paid vendor (Phase 9b).
DEFAULT_PROJECT_BUDGET_USD = 2.0
# Per-user ceiling across every project, once there are users (Phase 9c).
DEFAULT_USER_BUDGET_USD = 10.0
# Phase 14: when the first take misses its slot, how many takes to voice in
# all and keep the nearest; and how far off the slot counts as a miss.
DEFAULT_TAKES_PER_LINE = 3
DEFAULT_FIT_TOLERANCE = 0.05
# ElevenLabs bills by plan; this is the rate used for the USD estimate only.
# 0.30 per 1k characters is roughly Creator-plan overage.
DEFAULT_ELEVENLABS_USD_PER_1K = 0.30

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    data_dir: Path
    elevenlabs_api_key: str | None = None
    elevenlabs_model: str = DEFAULT_ELEVENLABS_MODEL
    elevenlabs_voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID
    # Per-project ceiling on billed ElevenLabs characters. Every paid call is
    # charged against it *before* it is made.
    voice_budget_chars: int = DEFAULT_VOICE_BUDGET_CHARS
    # When set, no paid generation vendor is ever called, whatever keys exist.
    dry_run: bool = False
    max_regenerations: int = DEFAULT_MAX_REGENERATIONS
    anthropic_api_key: str | None = None
    # Required when the key is not scoped to a workspace (the API says so).
    anthropic_workspace_id: str | None = None
    project_budget_usd: float = DEFAULT_PROJECT_BUDGET_USD
    elevenlabs_usd_per_1k: float = DEFAULT_ELEVENLABS_USD_PER_1K
    takes_per_line: int = DEFAULT_TAKES_PER_LINE
    fit_tolerance: float = DEFAULT_FIT_TOLERANCE
    # Phase 9c: "off" keeps the single local owner; "google" requires sign-in.
    auth_mode: str = "off"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    session_secret: str | None = None
    # The origin the browser uses, for the OAuth redirect: https://voltage.example.com
    public_url: str = "http://localhost:5173"
    # Who may sign in: emails or @domains, comma-separated. Empty = anyone with a Google account.
    allowed_emails: tuple[str, ...] = ()
    # Per-user ceiling on estimated spend across all their projects.
    user_budget_usd: float = DEFAULT_USER_BUDGET_USD

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_elevenlabs(self) -> bool:
        return bool(self.elevenlabs_api_key)


def _whole_number(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{name} must be a whole number >= 0, got {raw!r}")
    return value


def _amount(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value < 0:
        raise ValueError(f"{name} must be an amount >= 0, got {raw!r}")
    return value


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        data_dir=Path(os.environ.get("AVE_DATA_DIR", BACKEND_ROOT / "var")),
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY") or None,
        elevenlabs_model=os.environ.get("ELEVENLABS_MODEL") or DEFAULT_ELEVENLABS_MODEL,
        elevenlabs_voice_id=os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_ELEVENLABS_VOICE_ID,
        voice_budget_chars=_whole_number("AVE_VOICE_BUDGET_CHARS", DEFAULT_VOICE_BUDGET_CHARS),
        dry_run=os.environ.get("AVE_DRY_RUN", "").strip().lower() in _TRUTHY,
        max_regenerations=_whole_number("AVE_MAX_REGENERATIONS", DEFAULT_MAX_REGENERATIONS),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
        project_budget_usd=_amount("AVE_PROJECT_BUDGET_USD", DEFAULT_PROJECT_BUDGET_USD),
        elevenlabs_usd_per_1k=_amount("AVE_ELEVENLABS_USD_PER_1K", DEFAULT_ELEVENLABS_USD_PER_1K),
        takes_per_line=max(1, _whole_number("AVE_TAKES_PER_LINE", DEFAULT_TAKES_PER_LINE)),
        fit_tolerance=_amount("AVE_FIT_TOLERANCE", DEFAULT_FIT_TOLERANCE),
        auth_mode=_auth_mode(),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
        session_secret=os.environ.get("AVE_SESSION_SECRET") or None,
        public_url=(os.environ.get("AVE_PUBLIC_URL") or "http://localhost:5173").rstrip("/"),
        allowed_emails=tuple(e.strip() for e in os.environ.get("AVE_ALLOWED_EMAILS", "").split(",") if e.strip()),
        user_budget_usd=_amount("AVE_USER_BUDGET_USD", DEFAULT_USER_BUDGET_USD),
    )


def _auth_mode() -> str:
    mode = (os.environ.get("AVE_AUTH") or "off").strip().lower()
    if mode not in ("off", "google"):
        raise ValueError(f"AVE_AUTH must be 'off' or 'google', got {mode!r}")
    if mode == "google":
        missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "AVE_SESSION_SECRET") if not os.environ.get(k)]
        if missing:
            raise ValueError(f"AVE_AUTH=google needs {', '.join(missing)}")
    return mode
