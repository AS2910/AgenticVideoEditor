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
DEFAULT_MAX_FLEX = 1.12         # Phase 16: the roadmap's undetectable band
DEFAULT_MAX_LIVING = 1.6        # how far a pause may stretch for an added line
DEFAULT_INTERPOLATOR = "minterpolate"
# ElevenLabs bills by plan; this is the rate used for the USD estimate only.
# 0.30 per 1k characters is roughly Creator-plan overage.
DEFAULT_ELEVENLABS_USD_PER_1K = 0.30

# Phase 15a: a clone needs this much of the speaker's own speech (ElevenLabs
# asks for about a minute for its best result; it accepts less, and a short
# clip's clone is rougher, which the measured match then says).
DEFAULT_CLONE_MIN_SECONDS = 10.0
DEFAULT_VOICE_ROUTE = "auto"    # Phase 15b: "tts" | "changer" | "auto"

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
    # Phase 16: how far the picture may slow or speed so a take fits (1.0 = never);
    # how far a pause may stretch to make room for an added line; and how the
    # frames in between are made ("minterpolate", "none", or "rife").
    max_flex: float = DEFAULT_MAX_FLEX
    max_living: float = DEFAULT_MAX_LIVING
    interpolator: str = DEFAULT_INTERPOLATOR
    # Phase 15: clone each speaker's voice (on by default whenever the vendor
    # is real); how much of their speech it takes; and how a take reaches the
    # clone — plain text-to-speech, the Voice Changer, or the first with the
    # second as the rung after a weak identity match.
    clone: bool = True
    # Phase 20: Voltage as an agent with tools (needs an Anthropic key). The
    # per-turn money cap, the model and its effort.
    agent: bool = True
    agent_turn_usd: float = 0.50
    agent_model: str = "claude-opus-5-5"
    agent_effort: str = "high"
    # A2: the project check's one cheap text pass over the transcripts.
    check_model: str = "claude-haiku-4-5"
    # Phase 15c: keep the original's music and room under an edited line, by
    # separating the voice from the bed (needs the optional `room` extra).
    stems: bool = True
    clone_min_seconds: float = DEFAULT_CLONE_MIN_SECONDS
    voice_route: str = DEFAULT_VOICE_ROUTE
    # Phase 9c: "off" keeps the single local owner; "google" requires sign-in
    # (Google or an account); "accounts" requires sign-in with an account (item 5).
    auth_mode: str = "off"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    session_secret: str | None = None
    # F6: the key share links are signed with; when unset, one is generated
    # once and kept in the data dir (`share_secret`).
    share_secret: str | None = None
    # C2: who sends email (`outbox` = the fake provider: nothing leaves the
    # machine, each email is a row in notify_outbox) and where the local
    # owner's review digest goes (a signed-in owner's is their Google email).
    email_provider: str = "outbox"
    notify_owner_email: str | None = None
    # Step 0 (FLAGS): the owners every phase flag is on for by default.
    flag_owners: tuple[str, ...] = ("local",)
    # G7: who sees the internal admin page (#admin): owners, comma-separated.
    admin_owners: tuple[str, ...] = ("local",)
    # G8: where errors would go. A Sentry-shaped DSN; the provider is NOT
    # connected (app/errors_report.py): reports stay in the log and the
    # local error_reports table until someone wires it (SETUP_NEEDED.md).
    sentry_dsn: str | None = None
    # G3: who issues invoices (placeholders until the business is set up:
    # SETUP_NEEDED.md). The state code decides CGST+SGST or IGST.
    seller_name: str = "Voltage (seller details not set)"
    seller_gstin: str = ""
    seller_state: str = "29"
    # G6: where abuse reports are emailed (the fake email provider until one is
    # set up), and how long a kept consent record outlives its voice or video
    # (D3 left it unset; 7 years until legal confirms: DECISIONS.md).
    trust_email: str = "trust@voltage.invalid"
    consent_retention_years: float = 7.0
    # D3: run the purge (Bin items older than 30 days) once a day from the
    # server. Off by default: `python -m app.purge` by hand.
    purge_daily: bool = False
    # The origin the browser uses, for the OAuth redirect: https://voltage.example.com
    public_url: str = "http://localhost:5173"
    # Who may sign in: emails or @domains, comma-separated. Empty = anyone with a Google account.
    allowed_emails: tuple[str, ...] = ()
    # Per-user ceiling on estimated spend across all their projects.
    user_budget_usd: float = DEFAULT_USER_BUDGET_USD
    # The chaos pass: faults to inject at the vendor seams (see app/chaos.py); never with sign-in on unless forced.
    chaos: str | None = None
    chaos_force: bool = False
    # Launch item 2: AVE_ENV=production reads secrets only from the real
    # environment (never backend/.env) and refuses to start without them.
    production: bool = False
    # Launch item 3: what everyone together may spend in a UTC day before new
    # paid work pauses on its own (None: no cap).
    daily_cap_usd: float | None = 50.0
    # Origins the browser may call the API from (CORS); the public URL by default.
    cors_origins: tuple[str, ...] = ()

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
    production = (os.environ.get("AVE_ENV") or "").strip().lower() == "production"
    if not production:
        load_dotenv()
    public_url = (os.environ.get("AVE_PUBLIC_URL") or "http://localhost:5173").rstrip("/")
    return Settings(
        production=production,
        daily_cap_usd=(None if (os.environ.get("AVE_DAILY_SPEND_CAP_USD") or "").strip().lower() in ("none", "off")
                       else _amount("AVE_DAILY_SPEND_CAP_USD", 50.0)),
        cors_origins=tuple(o.strip().rstrip("/") for o in (os.environ.get("AVE_CORS_ORIGINS") or public_url).split(",") if o.strip()),
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
        max_flex=max(1.0, _amount("AVE_MAX_FLEX", DEFAULT_MAX_FLEX)),
        max_living=max(1.0, _amount("AVE_MAX_LIVING", DEFAULT_MAX_LIVING)),
        interpolator=(os.environ.get("AVE_INTERPOLATOR") or DEFAULT_INTERPOLATOR).strip().lower(),
        stems=os.environ.get("AVE_STEMS", "1").strip().lower() not in {"0", "false", "no", "off"},
        clone=os.environ.get("AVE_CLONE", "1").strip().lower() not in {"0", "false", "no", "off"},
        agent=os.environ.get("AVE_AGENT", "1").strip().lower() in {"1", "true", "yes", "on"},
        agent_turn_usd=_amount("AVE_AGENT_TURN_USD", 0.50),
        agent_model=os.environ.get("AVE_AGENT_MODEL", "claude-opus-5-5").strip() or "claude-opus-5-5",
        agent_effort=os.environ.get("AVE_AGENT_EFFORT", "high").strip() or "high",
        check_model=os.environ.get("AVE_CHECK_MODEL", "claude-haiku-4-5").strip() or "claude-haiku-4-5",
        clone_min_seconds=_amount("AVE_CLONE_MIN_SECONDS", DEFAULT_CLONE_MIN_SECONDS),
        voice_route=_voice_route(),
        auth_mode=_auth_mode(),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
        session_secret=os.environ.get("AVE_SESSION_SECRET") or None,
        share_secret=os.environ.get("AVE_SHARE_SECRET") or None,
        email_provider=(os.environ.get("AVE_EMAIL_PROVIDER") or "outbox").strip().lower(),
        notify_owner_email=os.environ.get("AVE_NOTIFY_OWNER_EMAIL") or None,
        public_url=(os.environ.get("AVE_PUBLIC_URL") or "http://localhost:5173").rstrip("/"),
        allowed_emails=tuple(e.strip() for e in os.environ.get("AVE_ALLOWED_EMAILS", "").split(",") if e.strip()),
        chaos=os.environ.get("AVE_CHAOS") or None,
        chaos_force=os.environ.get("AVE_CHAOS_FORCE", "").strip().lower() in _TRUTHY,
        user_budget_usd=_amount("AVE_USER_BUDGET_USD", DEFAULT_USER_BUDGET_USD),
        flag_owners=tuple(o.strip() for o in os.environ.get("AVE_FLAG_OWNERS", "local").split(",") if o.strip()),
        sentry_dsn=os.environ.get("SENTRY_DSN") or None,
        seller_name=os.environ.get("AVE_SELLER_NAME") or "Voltage (seller details not set)",
        seller_gstin=(os.environ.get("AVE_SELLER_GSTIN") or "").strip().upper(),
        seller_state=(os.environ.get("AVE_SELLER_STATE") or "29").strip(),
        trust_email=os.environ.get("AVE_TRUST_EMAIL") or "trust@voltage.invalid",
        consent_retention_years=_amount("AVE_CONSENT_RETENTION_YEARS", 7.0),
        admin_owners=tuple(o.strip() for o in os.environ.get("AVE_ADMIN_OWNERS", "local").split(",") if o.strip()),
        purge_daily=os.environ.get("AVE_PURGE_DAILY", "").strip().lower() in _TRUTHY,
    )


def _voice_route() -> str:
    route = (os.environ.get("AVE_VOICE_ROUTE") or DEFAULT_VOICE_ROUTE).strip().lower()
    if route not in ("tts", "changer", "auto"):
        raise ValueError(f"AVE_VOICE_ROUTE must be 'tts', 'changer' or 'auto', got {route!r}")
    return route


def _auth_mode() -> str:
    mode = (os.environ.get("AVE_AUTH") or "off").strip().lower()
    # Launch item 5: "accounts" is sign-in with an email and password (and
    # emailed links) without Google; "google" offers both.
    if mode not in ("off", "google", "accounts"):
        raise ValueError(f"AVE_AUTH must be 'off', 'google' or 'accounts', got {mode!r}")
    if mode == "accounts" and not os.environ.get("AVE_SESSION_SECRET"):
        raise ValueError("AVE_AUTH=accounts needs AVE_SESSION_SECRET")
    if mode == "google":
        missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "AVE_SESSION_SECRET") if not os.environ.get(k)]
        if missing:
            raise ValueError(f"AVE_AUTH=google needs {', '.join(missing)}")
    return mode


# Launch item 2: what production cannot start without. Each entry: the
# variable, and why. Sign-in and the signing keys keep accounts and links
# safe; the vendor keys are the product; email carries sign-in links.
REQUIRED_IN_PRODUCTION = (
    ("AVE_SESSION_SECRET", "signs sign-in sessions"),
    ("AVE_SHARE_SECRET", "signs share links and media URLs (a generated file is not used in production)"),
    ("AVE_PUBLIC_URL", "the https address people open; links and sign-in redirects use it"),
    ("ANTHROPIC_API_KEY", "Voltage itself"),
    ("ELEVENLABS_API_KEY", "voicing lines"),
    ("OPENAI_API_KEY", "transcription"),
    ("AVE_EMAIL_PROVIDER", "sign-in, verification and reset emails (not the outbox)"),
)


def production_problems(env: dict[str, str] | None = None) -> list[str]:
    """Why production must not start, one sentence each (empty when it may)."""
    env = dict(os.environ if env is None else env)
    problems = [f"{name} is missing ({why})." for name, why in REQUIRED_IN_PRODUCTION if not (env.get(name) or "").strip()]
    if (env.get("AVE_PUBLIC_URL") or "").strip() and not env["AVE_PUBLIC_URL"].startswith("https://"):
        problems.append("AVE_PUBLIC_URL must be an https:// address.")
    if (env.get("AVE_EMAIL_PROVIDER") or "").strip().lower() == "outbox":
        problems.append("AVE_EMAIL_PROVIDER is outbox, which sends nothing.")
    for name in ("AVE_SESSION_SECRET", "AVE_SHARE_SECRET"):
        if 0 < len((env.get(name) or "").strip()) < 32:
            problems.append(f"{name} is too short (32 characters at least).")
    if (env.get("AVE_AUTH") or "off").strip().lower() == "off":
        problems.append("AVE_AUTH is off, so anyone could use the one local account.")
    if (env.get("AVE_CHAOS") or "").strip():
        problems.append("AVE_CHAOS injects faults; unset it.")
    if (env.get("AVE_DRY_RUN") or "").strip().lower() in _TRUTHY:
        problems.append("AVE_DRY_RUN is on, so no paid step would run.")
    return problems


def ensure_production_ready(settings: Settings) -> None:
    """Fail fast: raise with every problem at once."""
    if not settings.production:
        return
    problems = production_problems()
    if problems:
        raise RuntimeError("Voltage will not start in production:\n- " + "\n- ".join(problems))
