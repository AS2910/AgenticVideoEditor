"""How Voltage talks (2026-10-20): a lint for its closing words.

The style guide in the system prompt asks for the creative result first, in
the video's own terms, two sentences at most (run 5 item 5; it was three),
facts in one compact line at the end, and no internal words (slot, take c3,
item i1, turn cap, edit e2, model names, dB) unless the user asked. This
checks the words it wrote; the eval counts the issues, and every turn logs
them.

Run 5 item 5: the lint only flags, it never rewrites. What the person reads
is cut by `split`: the first two sentences stand in the thread, the rest (and
the facts line) waits behind "Why?". Nothing is deleted, so a reply that runs
long still says everything, one click away.
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
MAX_SENTENCES = 2
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
# Asked for the long version: an explanation, the reasons, or how to do something (Help).
_MORE = re.compile(r"\b(explain|why|details?|more)\b|\bhow (?:do|can|does|should)\b", re.I)
# A correction (reply_check) contradicts what was said; it always stands in view.
_CORRECTION = re.compile(r"^Correction:")


def asked_for_more(user_text: str) -> bool:
    return bool(_MORE.search(user_text or ""))


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
    if n > MAX_SENTENCES and not asked_for_more(user_text):
        issues.append(f"{n} sentences")
    return issues


def split(reply: str, user_text: str = "") -> tuple[str, str]:
    """(what stands in the thread, what waits behind "Why?"). The first two prose
    sentences, plus any correction, stand; the other sentences and the facts line
    ("0:00 to 0:16 · four lines · $0.38") move behind Why?. A reply that fits, or one
    the user asked to be long, comes back whole with nothing behind Why?."""
    text = (reply or "").strip()
    if not text or asked_for_more(user_text):
        return text, ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    facts = [ln for ln in lines if "·" in ln]
    prose = [s.strip() for s in _SENT.split(" ".join(ln for ln in lines if "·" not in ln)) if s.strip()]
    head: list[str] = []
    rest: list[str] = []
    for s in prose:
        (head if _CORRECTION.match(s) or sum(not _CORRECTION.match(h) for h in head) < MAX_SENTENCES else rest).append(s)
    if not head or (not rest and not facts):
        return text, ""
    why = "\n".join(x for x in (" ".join(rest), *facts) if x)
    return " ".join(head), why
