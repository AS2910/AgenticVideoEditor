"""Story checks after a quick edit (run 5 item 6): local, free, and never a block.

A line changed the quick way skips Voltage's planning, so nothing has read the
rest of the video against the new words. Two checks run after the take is
proposed, on the words alone (no Claude call, nothing charged):

- a repeated phrase: three or more words in a row that another line already
  says ("today only" twice is a choice; "get it today only" twice reads as a slip);
- a contradiction: a percentage or a price that another line states
  differently ("30% off" here, "20% off" at 0:12), or the same words with one
  of them negated ("it is ready" / "it is not ready").

Each finding is one plain sentence naming the other line's time; the editor
shows them as a gentle suggestion in Voltage's pane. Being heuristics, they
can miss things a reading would catch, and they can fire on a repeat the
writer meant; the sentence says "if you meant it, leave it".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# Words too common to make a repeat worth pointing out on their own.
_STOP = frozenset("""a an the and or but so to of in on at for with from by is are was were be been it its this that
these those i you he she we they me my your our their his her them us as if then than there here just very
""".split())
_NEGATORS = frozenset({"not", "no", "never", "none", "nothing", "nobody", "cannot"})
_WORD = re.compile(r"[a-z0-9$%']+(?:\.[0-9]+)?")
# "30%", "30 percent", "$4.99", "4.99 dollars", "Rs 499", "€5".
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b|per cent\b)", re.IGNORECASE)
_MONEY = re.compile(r"(?:[$€£₹]|\brs\.?\s?|\binr\s?)(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:dollars|euros|pounds|rupees)\b",
                    re.IGNORECASE)
MIN_RUN = 3


@dataclass(frozen=True)
class StoryLine:
    start: float
    text: str


def _tokens(text: str) -> list[str]:
    words = []
    for w in _WORD.findall(text.lower().replace("’", "'")):
        if w.endswith("n't"):
            words.extend([w[:-3] or w, "not"])
        else:
            words.append(w)
    return words


def _clock(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _runs(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def repeated_phrase(new_text: str, other: str) -> str | None:
    """The longest run of MIN_RUN+ words the new line shares with `other`,
    when at least one of its words is more than filler; else None."""
    a, b = _tokens(new_text), _tokens(other)
    for n in range(min(len(a), len(b)), MIN_RUN - 1, -1):
        shared = _runs(a, n) & _runs(b, n)
        for run in sorted(shared):
            if any(w not in _STOP and w not in _NEGATORS for w in run):
                return " ".join(run)
    return None


def _values(pattern: re.Pattern, text: str) -> set[str]:
    out = set()
    for m in pattern.finditer(text):
        raw = next(g for g in m.groups() if g)
        out.add(raw.replace(",", "").rstrip("0").rstrip(".") if "." in raw else raw.replace(",", ""))
    return out


def _negation_flip(new_text: str, other: str) -> str | None:
    """The same run of words in both lines once negators are set aside, with a
    negator in only one of them: "it is ready" against "it is not ready"."""
    a, b = _tokens(new_text), _tokens(other)
    neg_a, neg_b = any(w in _NEGATORS for w in a), any(w in _NEGATORS for w in b)
    if neg_a == neg_b:
        return None
    plain_a = [w for w in a if w not in _NEGATORS]
    plain_b = [w for w in b if w not in _NEGATORS]
    return repeated_phrase(" ".join(plain_a), " ".join(plain_b))


def check(lines: Sequence[StoryLine], changed_start: float, new_text: str) -> list[str]:
    """What reads oddly against the rest of the video once this line says
    `new_text`: at most one sentence per other line, nearest first, at most three."""
    found: list[tuple[float, str]] = []
    pct, money = _values(_PERCENT, new_text), _values(_MONEY, new_text)
    for ln in lines:
        if abs(ln.start - changed_start) < 0.01 or not ln.text.strip():
            continue
        at = _clock(ln.start)
        other_pct, other_money = _values(_PERCENT, ln.text), _values(_MONEY, ln.text)
        if pct and other_pct and not (pct & other_pct):
            found.append((ln.start, f"The line at {at} still says {sorted(other_pct)[0]}%, and this one now says {sorted(pct)[0]}%."))
            continue
        if money and other_money and not (money & other_money):
            found.append((ln.start, f"The line at {at} gives a different price ({ln.text.strip()[:60]})."))
            continue
        flip = _negation_flip(new_text, ln.text)
        if flip:
            found.append((ln.start, f"The line at {at} says the opposite about “{flip}”."))
            continue
        run = repeated_phrase(new_text, ln.text)
        if run:
            found.append((ln.start, f"“{run}” is also said at {at}."))
    found.sort(key=lambda f: abs(f[0] - changed_start))
    return [sentence for _, sentence in found[:3]]


def suggestion(findings: Sequence[str]) -> str | None:
    """The gentle note Voltage's pane shows, or None when nothing reads oddly."""
    if not findings:
        return None
    return "Worth a look: " + " ".join(findings) + " If you meant it, leave it."
