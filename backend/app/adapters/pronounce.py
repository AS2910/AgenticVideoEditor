"""Pronunciation at the voice adapter boundary (A3).

A project's word rules can carry a respelling ("Bhaji Cam" -> "BAH-jee cam").
The text sent to the voice vendor has each term replaced by its respelling;
the line's display text, the plan and the edit keep the words as written.

ElevenLabs offers pronunciation dictionaries (alias rules, phoneme tags on
some models), but they live at the vendor and must be created and kept in
step first; an alias rule is exactly this substitution, so the rewrite is
done here, for every adapter, without a vendor round trip (DECISIONS.md, A3).

    with respelling(pairs):          # around one take
        sent = for_synthesis(text)   # inside the adapter
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable, Iterator

_PAIRS: ContextVar[tuple[tuple[str, str], ...]] = ContextVar("respellings", default=())


def pairs_from(rules: Iterable[dict]) -> tuple[tuple[str, str], ...]:
    """(term, respelling) for every pronounce rule that has a respelling,
    longest term first so "Bhaji Cam Pro" wins over "Bhaji Cam"."""
    pairs = {(str(d["term"]).strip(), str(d["respell"]).strip())
             for r in rules if r.get("kind") == "pronounce"
             for d in [r.get("data") or {}] if d.get("term") and d.get("respell")}
    return tuple(sorted(pairs, key=lambda p: (-len(p[0]), p[0])))


@contextmanager
def respelling(pairs: Iterable[tuple[str, str]]) -> Iterator[None]:
    token = _PAIRS.set(tuple(pairs))
    try:
        yield
    finally:
        _PAIRS.reset(token)


def for_synthesis(text: str, pairs: Iterable[tuple[str, str]] | None = None) -> str:
    """The words the vendor is asked to say: each term (whole words, any
    case) replaced by its respelling. Unchanged when there are none."""
    for term, respell in (_PAIRS.get() if pairs is None else tuple(pairs)):
        text = re.sub(rf"(?<![\w]){re.escape(term)}(?![\w])", respell, text, flags=re.IGNORECASE)
    return text
