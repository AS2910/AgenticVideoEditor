"""How Voltage talks (2026-10-20): a lint for its closing words.

The style guide in the system prompt asks for the creative result first, in
the video's own terms, three sentences by default, facts in one compact line
at the end, and no internal words (slot, take c3, item i1, turn cap, edit e2,
model names, dB) unless the user asked. This checks the words it wrote; the
eval counts the issues, and every turn logs them.
"""
from __future__ import annotations

import re

BANNED = [
    (re.compile(r"\bslots?\b", re.I), "slot"),
    (re.compile(r"\btakes?\s+c\d+\b|\bc\d+\b"), "a take id"),
    (re.compile(r"\bitems?\s+i\d+\b|\bi\d+\b"), "an item id"),
    (re.compile(r"\bedits?\s+e\d+\b|\be\d+\b"), "an edit id"),
    (re.compile(r"\bturn(?:'s)?\s+(?:\$[\d.]+\s+)?cap\b", re.I), "turn cap"),
    (re.compile(r"\b(claude|opus|sonnet|haiku|eleven_[a-z0-9_]+|eleven v\d)\b", re.I), "a model name"),
    (re.compile(r"[-+−]?\d+(?:\.\d+)?\s?dB\b"), "dB"),
]
MAX_SENTENCES = 3
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")


def sentences(text: str) -> list[str]:
    """The prose sentences; a closing facts line ("0:00 to 0:16 · four lines · $0.38") is not one."""
    body = [ln for ln in (text or "").strip().splitlines() if ln.strip() and "·" not in ln]
    return [s for s in _SENT.split(" ".join(body)) if s.strip()]


def lint(reply: str, user_text: str = "") -> list[str]:
    """What the closing words break, as short notes; empty when they are fine."""
    if not reply:
        return []
    issues = []
    asked_db = bool(re.search(r"\bdb\b|decibel|how loud", user_text or "", re.I))
    for pattern, name in BANNED:
        if name == "dB" and asked_db:
            continue
        if pattern.search(reply):
            issues.append(f"uses {name}")
    n = len(sentences(reply))
    if n > MAX_SENTENCES and not re.search(r"\b(explain|why|detail|more)\b", user_text or "", re.I):
        issues.append(f"{n} sentences")
    return issues
