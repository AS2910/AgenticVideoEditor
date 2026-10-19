"""No em dashes in Voltage's own prose (2026-10-19).

The prompts tell the model not to write them; this is the safety net, run on
what Voltage says (closing replies, questions, step lines, its first read of a
clip). It never touches words to be spoken, anything the user typed, or a
quote inside Voltage's reply: quoted spans (“…”, "…") pass through as they
are. When the user's own message uses an em dash or asks for one, Voltage may
match them and nothing is changed.
"""
from __future__ import annotations

import re

DASHES = re.compile(r"\s*(?:—|&mdash;)\s*|\s+--\s+")
QUOTED = re.compile(r"“[^”]*”|\"[^\"\n]*\"")
ASKS_FOR_DASHES = re.compile(r"—|&mdash;|\bem[\s-]?dash", re.I)


def wants_dashes(user_text: str | None) -> bool:
    """The user wrote an em dash, or asked for them: Voltage may match."""
    return bool(user_text) and ASKS_FOR_DASHES.search(user_text or "") is not None


def _swap(part: str) -> str:
    out = DASHES.sub(", ", part)
    # A dash next to other punctuation leaves a doubled mark: keep the stronger one.
    out = re.sub(r",\s*([,.;:!?])", r"\1", out)
    out = re.sub(r"([.;:!?])\s*,\s*", r"\1 ", out)
    return re.sub(r"^\s*,\s*", "", out)


def plain(text: str | None, user_text: str | None = None) -> str | None:
    """`text` with Voltage's em dashes turned into commas, quotes left alone."""
    if not text or wants_dashes(user_text) or not DASHES.search(text):
        return text
    out, last = [], 0
    for m in QUOTED.finditer(text):
        out.append(_swap(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_swap(text[last:]))
    return "".join(out)
