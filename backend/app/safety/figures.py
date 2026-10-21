"""G6: no clones of public figures.

    check.match(name) -> str | None     the listed figure a name matches, or None

`ListCheck` reads a small built-in list (`public_figures.txt`, one name a
line, `#` comments) and matches a speaker or voice name when every word of a
listed name appears in it, ignoring case, accents, punctuation and order.
It is a fake: a real provider would compare the voice itself against known
voices (SETUP_NEEDED.md). The refusal is one sentence, `REFUSAL`.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Protocol

LIST = Path(__file__).with_name("public_figures.txt")
REFUSAL = ("Voltage does not clone the voices of public figures. Pick a voice from the catalogue, "
           "or design one from words.")


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


class PublicFigureCheck(Protocol):
    name: str

    def match(self, name: str) -> str | None: ...


class ListCheck:
    name = "built-in list"

    def __init__(self, path: Path = LIST) -> None:
        self.figures = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        self._sets = [(f, set(_words(f))) for f in self.figures]

    def match(self, name: str) -> str | None:
        have = set(_words(name))
        if not have:
            return None
        for figure, words in self._sets:
            if words and words <= have:
                return figure
        return None
