"""Launch item 8: every environment variable the backend reads is listed in
the repo root's `.env.example`, so a new one cannot ship undocumented."""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
EXAMPLE = BACKEND.parent / ".env.example"
# os.environ.get("X"), os.environ["X"], os.getenv("X"), env.get("X") and
# config.py's _whole_number("X", ...) / _amount("X", ...).
READ = re.compile(r"""(?:environ(?:\.get)?\s*(?:\(|\[)|getenv\s*\(|\benv\.get\s*\(|_whole_number\s*\(|_amount\s*\()\s*["']([A-Z][A-Z0-9_]+)["']""")
# config.py checks these by name in a tuple when AVE_AUTH=google.
ALSO = re.compile(r"""for k in \(([^)]*)\) if not os\.environ""")


def names_read() -> set[str]:
    names: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        names |= set(READ.findall(text))
        for group in ALSO.findall(text):
            names |= set(re.findall(r"""["']([A-Z][A-Z0-9_]+)["']""", group))
    return names


def names_listed() -> set[str]:
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M))


def test_the_scan_finds_the_known_reads():
    found = names_read()
    assert {"AVE_DATA_DIR", "AVE_AUTH", "OPENAI_API_KEY", "AVE_VOICE_BUDGET_CHARS", "AVE_FFMPEG_BIN",
            "SENTRY_DSN", "AVE_WORKER_DIGESTS"} <= found


def test_every_variable_read_is_in_env_example():
    missing = sorted(names_read() - names_listed())
    assert missing == [], f"add these to .env.example with a one-line comment: {missing}"


def test_env_example_also_names_the_database_url():
    assert "DATABASE_URL" in names_listed()
