"""The project check (A2): what the videos in one project say, held against
each other and against the project's words. Transcripts and shipped edits
only; no new audio, no vendor.

    deterministic(videos, rules, voice_names) -> CheckResult(issues, notes)
    request_text(videos)                      -> what the Claude text pass reads
    estimate(videos, model)                   -> {"usd", "label", "input_tokens", "output_tokens"}
    from_model(raw, videos)                   -> [issue] (the text pass's issues, checked against the videos)
    fingerprint(kind, key, basis)             -> str

Deterministic, free checks: facts that disagree between videos (prices,
percentages, dates, phone numbers, web addresses, found by pattern), one
role voiced by different voices, a glossary term a take did not say as
written (A3's word check on the take's own words), a banned word said, a
required line missing, loudness more than 2 LU apart. The Claude text pass
adds what a pattern cannot see: offer names that disagree.

An issue is {kind, message, places: [{video_id, filename, t, text}],
fingerprint}. The fingerprint is the kind, its key and the text it was found
in, hashed: an ignored issue stays ignored until that text changes.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from app.agent import word_rules
from app.usage import claude_usd

LOUDNESS_GAP_LU = 2.0
# The text pass's reply is a short list; this is what the estimate assumes it
# writes (the call's max_tokens caps it at CHECK_MAX_TOKENS).
EXPECTED_OUTPUT_TOKENS = 400
CHECK_MAX_TOKENS = 2000
# Characters per token for English text, for the estimate before the call.
CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class Passage:
    """One piece of what a video says now: a line as shot (not replaced) or a
    shipped edit's words, with where it starts in the source."""
    text: str
    t: float
    source: str = "transcript"          # transcript | edit
    speaker: str | None = None          # the role's name; None when unnamed ("Speaker A")
    voice_id: str | None = None         # an edit's voice
    heard: tuple[str, ...] = ()         # an edit's take, as the vendor aligned its words


@dataclass(frozen=True)
class VideoText:
    video_id: str
    filename: str
    passages: tuple[Passage, ...]
    loudness_lufs: float | None = None  # the latest render's mix report; None: no render measured


@dataclass
class CheckResult:
    issues: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def clock(t: float | None) -> str:
    if t is None:
        return ""
    return f"{int(t // 60)}:{int(t % 60):02d}"


def fingerprint(kind: str, key: str, basis: Iterable[str]) -> str:
    body = "\n".join([kind, key, *sorted(basis)])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


def _place(v: VideoText, p: Passage | None) -> dict:
    return {"video_id": v.video_id, "filename": v.filename, "t": None if p is None else round(p.t, 2),
            "text": "" if p is None else p.text}


def _issue(kind: str, key: str, message: str, places: list[dict], basis: Iterable[str] | None = None) -> dict:
    basis = list(basis) if basis is not None else [f"{p['video_id']}|{p['text']}" for p in places]
    return {"kind": kind, "message": message, "places": places, "fingerprint": fingerprint(kind, key, basis)}


def _names(files: Sequence[str]) -> str:
    files = list(dict.fromkeys(files))
    return files[0] if len(files) == 1 else ", ".join(files[:-1]) + " and " + files[-1]


# ── facts, by pattern ────────────────────────────────────────────────────────

_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_PRICE = re.compile(
    rf"(?:(?P<cur>[₹$€£]|\brs\.?|\binr\b|\busd\b)\s?(?P<a>{_NUM})|(?P<b>{_NUM})\s?(?P<word>rupees\b|rs\b\.?|dollars\b|euros\b|pounds\b))",
    re.I)
_PERCENT = re.compile(rf"(?P<n>{_NUM})\s?(?:%|per\s?cent\b)", re.I)
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s-]{8,16}\d(?![\w])")
_URL = re.compile(r"\b(?:https?://)?(?:www\.)?[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|in|co|org|net|io|app|shop|store|ai)\b(?:/[^\s,]*)?", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = r"(?P<m>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_DM = re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b", re.I)
_DATE_MD = re.compile(rf"\b{_MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
_DATE_NUM = re.compile(r"\b(?P<d>\d{1,2})/(?P<mo>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")
_CURRENCY = {"₹": "₹", "rs": "₹", "rs.": "₹", "inr": "₹", "rupees": "₹", "$": "$", "usd": "$", "dollars": "$",
             "€": "€", "euros": "€", "£": "£", "pounds": "£"}

FACT_WORDS = {"price": "price", "percent": "percentage", "date": "date", "phone": "phone number", "url": "web address"}


def _amount(n: str) -> str:
    n = n.replace(",", "")
    return n[:-3] if n.endswith(".00") else n


def facts(text: str) -> dict[str, list[str]]:
    """Every fact in a piece of text, normalised: {"price": ["₹499"], ...}."""
    found: dict[str, list[str]] = {}
    said = re.sub(r"\s+dot\s+(?=[a-z])", ".", text, flags=re.I)
    rest = said
    for m in _URL.finditer(said):
        url = re.sub(r"^(?:https?://)?(?:www\.)?", "", m.group(0).lower()).rstrip("/.")
        found.setdefault("url", []).append(url)
        rest = rest.replace(m.group(0), " ")
    for m in _PHONE.finditer(rest):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= 10:
            found.setdefault("phone", []).append(digits[-10:])
            rest = rest.replace(m.group(0), " ")
    for m in _PRICE.finditer(rest):
        cur = (m.group("cur") or m.group("word") or "").lower().rstrip()
        found.setdefault("price", []).append(_CURRENCY.get(cur, _CURRENCY.get(cur.rstrip("."), "")) + _amount(m.group("a") or m.group("b")))
    for m in _PERCENT.finditer(rest):
        found.setdefault("percent", []).append(_amount(m.group("n")) + "%")
    for pattern in (_DATE_DM, _DATE_MD):
        for m in pattern.finditer(rest):
            day = int(m.group("d"))
            if 1 <= day <= 31:
                found.setdefault("date", []).append(f"{day} {m.group('m')[:3].title()}")
    for m in _DATE_NUM.finditer(rest):
        day, month = int(m.group("d")), int(m.group("mo"))
        if 1 <= day <= 31 and 1 <= month <= 12:
            found.setdefault("date", []).append(f"{day} {_MONTHS[month - 1].title()}")
    return {k: list(dict.fromkeys(v)) for k, v in found.items()}


def _fact_issues(videos: Sequence[VideoText]) -> list[dict]:
    out = []
    for kind, word in FACT_WORDS.items():
        # value -> [(video, passage)], first mention per video; per video the set of values it says.
        where: dict[str, list[tuple[VideoText, Passage]]] = {}
        sets: dict[str, set[str]] = {}
        for v in videos:
            for p in v.passages:
                for value in facts(p.text).get(kind, ()):
                    sets.setdefault(v.video_id, set()).add(value)
                    if not any(w.video_id == v.video_id for w, _ in where.get(value, ())):
                        where.setdefault(value, []).append((v, p))
        if len(sets) < 2 or len({frozenset(s) for s in sets.values()}) == 1:
            continue
        values = sorted(where, key=lambda val: min(videos.index(w) for w, _ in where[val]))
        said = "; ".join(f"{val} in {_names([w.filename for w, _ in where[val]])}" for val in values)
        places = [_place(w, p) for val in values for w, p in where[val]]
        out.append(_issue("fact", f"fact:{kind}", f"The videos give different {word}s: {said}.", places))
    return out


# ── one role, one voice ──────────────────────────────────────────────────────

def _voice_issues(videos: Sequence[VideoText], name_of: Callable[[str], str | None]) -> list[dict]:
    roles: dict[str, dict[str, list[tuple[VideoText, Passage]]]] = {}
    shown: dict[str, str] = {}
    for v in videos:
        for p in v.passages:
            if p.source != "edit" or not p.speaker or not p.voice_id:
                continue
            key = p.speaker.strip().lower()
            shown.setdefault(key, p.speaker.strip())
            by_voice = roles.setdefault(key, {})
            if not any(w.video_id == v.video_id for w, _ in by_voice.get(p.voice_id, ())):
                by_voice.setdefault(p.voice_id, []).append((v, p))
    out = []
    for key, by_voice in roles.items():
        if len(by_voice) < 2:
            continue
        files = {w.video_id for hits in by_voice.values() for w, _ in hits}
        if len(files) < 2:
            continue   # one video speaking a role in two voices is that video's own choice
        said = "; ".join(f"{name_of(vid) or 'voice ' + vid[:8]} in {_names([w.filename for w, _ in hits])}"
                         for vid, hits in by_voice.items())
        places = [_place(w, p) for hits in by_voice.values() for w, p in hits]
        basis = [f"{w.video_id}|{vid}|{p.text}" for vid, hits in by_voice.items() for w, p in hits]
        out.append(_issue("voice", f"voice:{key}", f"“{shown[key]}” is voiced by {len(by_voice)} different voices: {said}.", places, basis))
    return out


# ── the project's words ──────────────────────────────────────────────────────

def _rules(rules: Iterable[dict], kind: str) -> list[dict]:
    return [r.get("data") or {} for r in rules if r.get("kind") == kind]


def _word_issues(videos: Sequence[VideoText], rules: Sequence[dict]) -> list[dict]:
    out = []
    for d in _rules(rules, "pronounce"):
        rule = [{"kind": "pronounce", "data": d}]
        hits = [(v, p) for v in videos for p in v.passages
                if p.source == "edit" and p.heard and not word_rules.check_take(p.text, p.heard, rule).ok]
        if hits:
            places = [_place(v, p) for v, p in hits]
            basis = [f"{v.video_id}|{p.text}|{' '.join(p.heard)}" for v, p in hits]
            out.append(_issue("pronounce", f"pronounce:{str(d.get('term')).lower()}",
                              f"“{d.get('term')}” did not come out as written ({d.get('say') or 'the project way'}) in {_names([v.filename for v, _ in hits])}.",
                              places, basis))
    for d in _rules(rules, "banned"):
        word = word_rules.tokens(str(d.get("word") or ""))
        hits = [(v, p) for v in videos for p in v.passages if word and word_rules._has(word_rules.tokens(p.text), word)]
        if hits:
            out.append(_issue("banned", f"banned:{' '.join(word)}",
                              f"“{d.get('word')}” is a banned word in this project; it is said in {_names([v.filename for v, _ in hits])}.",
                              [_place(v, p) for v, p in hits]))
    for d in _rules(rules, "required_line"):
        line = word_rules.tokens(str(d.get("text") or ""))
        missing = [v for v in videos if line and not word_rules._has(word_rules.tokens(" ".join(p.text for p in v.passages)), line)]
        if missing:
            basis = [f"{v.video_id}|{' '.join(p.text for p in v.passages)}" for v in missing]
            out.append(_issue("required_line", f"required_line:{' '.join(line)}",
                              f"“{d.get('text')}” is a required line, and {_names([v.filename for v in missing])} "
                              f"{'does' if len(missing) == 1 else 'do'} not say it.",
                              [_place(v, None) for v in missing], basis))
    return out


# ── loudness ────────────────────────────────────────────────────────────────

def _loudness(videos: Sequence[VideoText]) -> tuple[list[dict], list[str]]:
    measured = [v for v in videos if v.loudness_lufs is not None]
    unmeasured = [v.filename for v in videos if v.loudness_lufs is None]
    notes = []
    if unmeasured:
        notes.append(f"Loudness not checked for {_names(unmeasured)}: no render measured yet.")
    if len(measured) < 2:
        return [], notes
    loud = max(measured, key=lambda v: v.loudness_lufs)
    quiet = min(measured, key=lambda v: v.loudness_lufs)
    gap = loud.loudness_lufs - quiet.loudness_lufs
    if gap <= LOUDNESS_GAP_LU:
        return [], notes
    message = (f"{loud.filename} is {gap:.1f} LU louder than {quiet.filename} "
               f"({loud.loudness_lufs:.1f} against {quiet.loudness_lufs:.1f} LUFS). Videos in a set should sit within {LOUDNESS_GAP_LU:.0f} LU.")
    basis = [f"{v.video_id}|{v.loudness_lufs:.1f}" for v in measured]
    return [_issue("loudness", "loudness", message, [_place(loud, None), _place(quiet, None)], basis)], notes


def deterministic(videos: Sequence[VideoText], rules: Sequence[dict],
                  voice_names: dict[str, str] | Callable[[str], str | None] | None = None) -> CheckResult:
    """Every free check, in a fixed order (facts, voices, words, loudness).
    `voice_names` names a voice id (a dict, or a lookup asked only when a
    role is voiced differently)."""
    videos = list(videos)
    result = CheckResult()
    if len(videos) < 2:
        result.notes.append("Facts, voices and loudness are compared between videos; this project has fewer than two.")
    result.issues += _fact_issues(videos)
    names = voice_names or {}
    result.issues += _voice_issues(videos, names.get if isinstance(names, dict) else names)
    result.issues += _word_issues(videos, rules)
    loud, notes = _loudness(videos)
    result.issues += loud
    result.notes += notes
    return result


# ── the Claude text pass ─────────────────────────────────────────────────────

SYSTEM = """\
You check a set of short videos from one campaign for things they say \
differently. You read what each video says now, line by line with its time. \
Report only offer, sale, product or brand names that disagree between videos, \
for example "Diwali Dhamaka sale" in one video and "Diwali Bonanza sale" in \
another, or one product called two names. Do not report prices, percentages, \
dates, phone numbers or web addresses: those are checked separately. Do not \
report a difference that is plainly on purpose (two different products in two \
videos). For each issue return `message`, one plain sentence naming both \
wordings and the videos, and `places`: each place it occurs, with `video_id` \
exactly as given and `quote`, the words copied exactly from that line. Return \
no issues when nothing disagrees. Never use em dashes; use commas, colons or \
full stops.\
"""


def request_text(videos: Sequence[VideoText]) -> str:
    blocks = []
    for v in videos:
        lines = "\n".join(f"[{clock(p.t)}] {p.text}" for p in sorted(v.passages, key=lambda p: p.t) if p.text.strip())
        blocks.append(f"Video {v.video_id} \"{v.filename}\":\n{lines or '(says nothing)'}")
    return "\n\n".join(blocks)


def estimate(videos: Sequence[VideoText], model: str) -> dict:
    """What the text pass would cost, from the size of what it reads and the
    model's list price (app.usage); rounded up to the cent."""
    input_tokens = math.ceil((len(SYSTEM) + len(request_text(videos))) / CHARS_PER_TOKEN)
    usd = claude_usd(model, input_tokens, EXPECTED_OUTPUT_TOKENS)
    cents = max(1, math.ceil(usd * 100 - 1e-9))
    return {"usd": round(usd, 6), "label": f"about ${cents / 100:.2f}", "input_tokens": input_tokens,
            "output_tokens": EXPECTED_OUTPUT_TOKENS, "model": model}


def _norm(text: str) -> str:
    return " ".join(word_rules.tokens(text))


def from_model(raw: Sequence[dict], videos: Sequence[VideoText]) -> list[dict]:
    """The text pass's issues, kept only where its quotes are really in the
    videos it names, and only when they span two videos or more."""
    by_id = {v.video_id: v for v in videos}
    out = []
    for item in raw or ():
        places, basis = [], []
        for pl in item.get("places") or ():
            v = by_id.get(str(pl.get("video_id") or "").strip())
            quote = _norm(str(pl.get("quote") or ""))
            if v is None or not quote:
                continue
            p = next((p for p in v.passages if quote in _norm(p.text)), None)
            if p is None or any(x["video_id"] == v.video_id and x["t"] == round(p.t, 2) for x in places):
                continue
            places.append(_place(v, p))
            basis.append(f"{v.video_id}|{p.text}")
        message = " ".join(str(item.get("message") or "").split()).replace("\u2014", ",")
        if len({p["video_id"] for p in places}) < 2 or not message:
            continue
        out.append(_issue("offer", "offer", message[:300], places, basis))
    return out
