"""The help articles (Tutorial map and Help, 2026-10-19): Markdown files under
`help/articles/<section>/<slug>.md` at the repo root, with front matter
(`title`, `section`, `order`, `tour`). The Help page and Voltage's
`search_help` tool read the same words, so neither can drift from the other.

Beta kit (2026-10-24): `help/known-issues.md` is the Known issues page (the
Beta badge links to it), with front matter (`title`, `updated`), a summary
paragraph and `## ` sections. It is not an article, so search never offers it
as an answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[3] / "help" / "articles"
KNOWN_ISSUES = ROOT.parent / "known-issues.md"


@dataclass(frozen=True)
class Article:
    slug: str
    section: str
    title: str
    summary: str
    body: str
    order: int
    tour: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _parse(path: Path) -> Article | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip():
            meta[k.strip()] = v.strip()
    rest = m.group(2).strip()
    summary, _, body = rest.partition("\n\n")
    try:
        order = int(meta.get("order", "0"))
    except ValueError:
        order = 0
    return Article(slug=path.stem, section=meta.get("section", path.parent.name), title=meta.get("title", path.stem),
                   summary=summary.strip(), body=body.strip(), order=order, tour=meta.get("tour") or None)


@lru_cache(maxsize=1)
def articles() -> tuple[Article, ...]:
    """Every article, in section order then article order. Cached: the files ship with the code."""
    if not ROOT.exists():
        return ()
    found = [a for p in sorted(ROOT.glob("*/*.md")) if (a := _parse(p)) is not None]
    return tuple(sorted(found, key=lambda a: (a.order, a.title)))


def by_slug(slug: str) -> Article | None:
    return next((a for a in articles() if a.slug == slug), None)


_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1]


def search(query: str, limit: int = 3) -> list[dict]:
    """The best-matching articles for a question, as dicts (`slug, section,
    title, summary, body, tour`). Scoring is plain word overlap, weighted
    towards the title and the summary; an empty match returns nothing rather
    than a guess."""
    words = set(_tokens(query))
    if not words:
        return []
    scored: list[tuple[float, Article]] = []
    for a in articles():
        title, summary, body = set(_tokens(a.title)), set(_tokens(a.summary)), set(_tokens(a.body + " " + a.section))
        score = 3.0 * len(words & title) + 2.0 * len(words & summary) + 1.0 * len(words & body)
        # The whole phrase inside the title or the summary is the strongest signal of all.
        q = query.strip().lower()
        if q and (q in a.title.lower() or q in a.summary.lower()):
            score += 5.0
        # A body-only brush with one common word is not an answer: the title or the summary must share a word, or two words must.
        if score >= 2.0 and (words & (title | summary) or len(words & body) >= 2):
            scored.append((score, a))
    scored.sort(key=lambda s: (-s[0], s[1].order))
    return [a.as_dict() for _, a in scored[:limit]]


router = APIRouter(tags=["help"])


@router.get("/help")
def list_articles() -> dict:
    """Every help article, for the Help page."""
    return {"articles": [a.as_dict() for a in articles()]}


@router.get("/help/search")
def search_articles(q: str = "", limit: int = 8) -> dict:
    """The articles that answer a question, best first."""
    return {"articles": search(q, limit=max(1, min(limit, 20)))}


def known_issues(path: Path | None = None) -> dict:
    """The Known issues page: title, updated, summary and its sections ({heading, body})."""
    path = path or KNOWN_ISSUES
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    meta: dict[str, str] = {}
    rest = text
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip():
                meta[k.strip()] = v.strip()
        rest = m.group(2)
    parts = re.split(r"^## +(.+)$", rest.strip(), flags=re.M)
    sections = [{"heading": h.strip(), "body": b.strip()} for h, b in zip(parts[1::2], parts[2::2])]
    return {"title": meta.get("title", "Known issues"), "updated": meta.get("updated") or None,
            "summary": parts[0].strip(), "sections": sections}


@router.get("/help/known-issues")
def get_known_issues() -> dict:
    """What we know is not right yet, for the Known issues page."""
    return known_issues()
