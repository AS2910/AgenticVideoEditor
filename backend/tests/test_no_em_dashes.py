"""CI check (2026-10-19): no em dash in anything Voltage writes or shows.

Scans the front end's source (outside comments; tests are not shown to
anyone), the backend's string literals (not docstrings or comments: those
are for the code's readers), the prompts, the help articles and the tutorial
fixture. A file that deliberately carries a user-supplied em dash goes in
ALLOWED with a reason."""
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = re.compile(r"—|&mdash;")
# path relative to the repo root -> why it may carry an em dash
ALLOWED: dict[str, str] = {
    "backend/app/agent/prose.py": "the pattern that finds em dashes in order to remove them",
}


def _python_hits(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    out = []
    for i, t in enumerate(toks):
        if t.type != tokenize.STRING or not DASH.search(t.string):
            continue
        prev = next((p for p in reversed(toks[:i]) if p.type not in (tokenize.NL, tokenize.COMMENT)), None)
        nxt = next((n for n in toks[i + 1:] if n.type not in (tokenize.NL, tokenize.COMMENT)), None)
        docstring = (prev is None or prev.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)) \
            and nxt is not None and nxt.type in (tokenize.NEWLINE, tokenize.ENDMARKER)
        if not docstring:
            out.append(f"{t.start[0]}: {t.string.strip()[:100]}")
    return out


def _without_comments(text: str) -> str:
    """Code without its comments, line by line: JSX text is full of apostrophes,
    so a quote-tracking lexer misreads it; comments here are always whole lines,
    block comments, JSX comments or a trailing `// …` after whitespace."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for line in text.splitlines():
        if line.strip().startswith("//"):
            out.append("")
            continue
        out.append(re.sub(r"(^|\s)//\s.*$", "", line))
    return "\n".join(out)


def _ts_hits(path: Path) -> list[str]:
    return [f"{no}: {line.strip()[:100]}" for no, line in enumerate(_without_comments(path.read_text(encoding="utf-8")).splitlines(), 1)
            if DASH.search(line)]


def _text_hits(path: Path) -> list[str]:
    return [f"{no}: {line.strip()[:100]}" for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if DASH.search(line)]


def _scan() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    files = [(p, _python_hits) for p in (ROOT / "backend/app").rglob("*.py")]
    files += [(p, _ts_hits) for p in (ROOT / "frontend/src").rglob("*.ts*") if ".test." not in p.name]
    files += [(p, _text_hits) for p in (ROOT / "help").rglob("*.md")]
    files += [(p, _text_hits) for p in (ROOT / "backend/app").rglob("*.json")]
    # Rehearsal item 7: the page shell (its tab title) and the static files beside it.
    files += [(ROOT / "frontend/index.html", _text_hits)]
    files += [(p, _text_hits) for p in (ROOT / "frontend/public").rglob("*.svg")]
    for path, scan in files:
        rel = str(path.relative_to(ROOT))
        if rel in ALLOWED:
            continue
        hits = scan(path)
        if hits:
            found[rel] = hits
    return found


def test_nothing_voltage_writes_or_shows_carries_an_em_dash():
    found = _scan()
    assert found == {}, "Em dashes in user-facing text (use a comma, a colon, a full stop or parentheses):\n" + "\n".join(
        f"  {rel}:{hit}" for rel, hits in found.items() for hit in hits)


def test_the_check_itself_sees_strings_and_ignores_comments(tmp_path):
    py = tmp_path / "a.py"
    py.write_text('"""Docs — fine."""\n# a comment — fine\nx = "shown — not fine"\n', encoding="utf-8")
    assert _python_hits(py) == ['3: "shown — not fine"']
    ts = tmp_path / "a.tsx"
    ts.write_text("// fine — here\nconst a = 'shown — no'\n/* also — fine */\n", encoding="utf-8")
    assert _ts_hits(ts) == ["2: const a = 'shown — no'"]
