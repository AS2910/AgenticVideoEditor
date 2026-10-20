"""The take check against the project's words (A3): before a take is kept,
its own words (the take's transcript) are held against the project's rules.

    check_take(text, heard, rules, typed="") -> WordCheck(breaks, warnings)
    check_text(text, rules)                  -> [warning sentences] (a line as typed)

A take breaks a rule when a glossary term in its line did not come out as
written or respelled (the take's words differ from the term), or when it
says a banned word Voltage wrote. A banned word the user typed themselves
is a warning, never a block: the line is theirs. Free and deterministic: no
model call, no vendor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

_TOKEN = re.compile(r"[\w%&'-]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    """Lower-case words, hyphens and apostrophes inside a word split off, so
    "BAH-jee" and "bah jee" compare equal."""
    out: list[str] = []
    for t in _TOKEN.findall(text.lower()):
        out.extend(p for p in re.split(r"[-']", t) if p)
    return out


def _has(seq: Sequence[str], sub: Sequence[str]) -> bool:
    if not sub:
        return False
    n = len(sub)
    return any(list(seq[i:i + n]) == list(sub) for i in range(len(seq) - n + 1))


def _joined(seq: Sequence[str], sub: Sequence[str]) -> bool:
    """`sub` said as one word or as its parts ("bhajicam" for "bhaji cam")."""
    return _has(seq, sub) or ("".join(sub) in seq)


@dataclass(frozen=True)
class WordCheck:
    breaks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    # B2: brand terms a language version's take translated (each is also a break).
    brand: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.breaks

    def to_dict(self) -> dict | None:
        """What the item carries; None when there is nothing to say."""
        if not self.breaks and not self.warnings:
            return None
        out: dict = {"breaks": list(self.breaks), "warnings": list(self.warnings)}
        if self.brand:
            out["brand"] = list(self.brand)
        return out

    def sentence(self) -> str:
        if self.breaks:
            return "Breaks a word rule: " + " ".join(self.breaks)
        return " ".join(self.warnings)


def _by_kind(rules: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rules:
        out.setdefault(r.get("kind") or "", []).append(r.get("data") or {})
    return out


def _heard_near(heard: Sequence[str], at_least: int = 4) -> str:
    return " ".join(heard[:max(at_least, 1)])


def check_take(text: str, heard: Sequence[str], rules: Iterable[dict], typed: str = "") -> WordCheck:
    """`text` is the line asked for, `heard` the take's own words in order
    (empty when the take has none to compare: nothing can be said about
    pronunciation then), `typed` what the user wrote this turn."""
    by = _by_kind(rules)
    said = tokens(text)
    got = [w for h in heard for w in tokens(h)]
    mine = tokens(typed)
    breaks: list[str] = []
    warnings: list[str] = []
    if got:
        for d in by.get("pronounce", []):
            term = tokens(str(d.get("term") or ""))
            if not term or not _has(said, term):
                continue
            ways = [term, tokens(str(d.get("respell") or "")), tokens(str(d.get("say") or ""))]
            if not any(w and _joined(got, w) for w in ways):
                breaks.append(f"“{d.get('term')}” did not come out as written (the take says “{_heard_near(got, len(said))}”).")
    for d in by.get("banned", []):
        word = tokens(str(d.get("word") or ""))
        if not word or not (_has(said, word) or _has(got, word)):
            continue
        if _has(mine, word):
            warnings.append(f"Uses “{d.get('word')}”, a banned word in this project. Kept, because you typed it.")
        else:
            breaks.append(f"Says “{d.get('word')}”, a banned word in this project.")
    return WordCheck(tuple(breaks), tuple(warnings))


def check_text(text: str, rules: Iterable[dict]) -> list[str]:
    """Warnings for a line as the user typed it: banned words in it. Never a block."""
    said = tokens(text)
    return [f"“{d.get('word')}” is a banned word in this project. You can still voice it."
            for d in _by_kind(rules).get("banned", []) if _has(said, tokens(str(d.get("word") or "")))]



# ── B2: language versions ────────────────────────────────────────────────────

def brand_terms(rules: Iterable[dict]) -> list[str]:
    """The project's words that never translate: glossary terms marked brand."""
    return [str(d.get("term")) for d in _by_kind(rules).get("pronounce", []) if d.get("brand") and d.get("term")]


def glossary_for(rules: Iterable[dict], lang: str) -> list[tuple[str, str]]:
    """(term, translation) for one language, from glossary entries naming it."""
    return [(str(d.get("term")), str(d.get("translation"))) for d in _by_kind(rules).get("pronounce", [])
            if d.get("lang") == lang and d.get("translation") and d.get("term") and not d.get("brand")]


def translated_brands(master_line: str, child_line: str, rules: Iterable[dict]) -> list[str]:
    """Brand terms the master's line says that the language version's line
    does not carry verbatim (as written, any case): each was translated or
    dropped. Free and deterministic."""
    said = tokens(master_line)
    lowered = child_line.lower()
    return [t for t in brand_terms(rules) if _has(said, tokens(t)) and t.lower() not in lowered]


def brand_breaks(missing: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"Brand name translated: “{t}” must stay as written." for t in missing)
