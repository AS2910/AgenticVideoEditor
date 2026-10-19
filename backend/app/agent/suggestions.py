"""The chips above Voltage's box (2026-10-20): suggestions from this video.

They come from the first read (one Claude call, structured output, no extra
call) and, after every turn, from Voltage's own closing message, which may
end with a `<next>` block of JSON that is taken off before the user sees the
words. Each chip is {label, prompt, kind, grounded_in}. Before any is shown
it is checked here:

- grounded: it points at a time, a word said, what the frames show, or the
  brief (`grounded_in` says which), and every name in it (a place, a brand,
  a person) is in the transcript, on screen, or in the brief, else it is
  dropped: a beach no one names is "this beach", never "Goa";
- short: the label is at most 40 characters;
- varied: at most one chip per kind (fix, change, add, voice, finish), four at most.

Without Claude (offline, a dry run) a small generic set by clip type is
shown, never another clip's specifics.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

KINDS = ("fix", "change", "add", "voice", "finish")
GROUNDS = ("time", "words", "frames", "brief")
MAX_LABEL = 40
MAX_CHIPS = 4

# Capitalised words that are not names: sentence starters, the app's own words, roles.
COMMON = {
    "a", "an", "the", "add", "say", "make", "try", "use", "give", "put", "tighten", "shorten", "fix", "change",
    "export", "introduce", "describe", "let", "keep", "voice", "line", "lines", "bed", "effect", "this", "that",
    "it", "its", "at", "in", "on", "for", "and", "or", "with", "to", "of", "a", "i", "my", "your", "our", "after",
    "before", "end", "start", "opening", "closing", "warmer", "calmer", "slower", "faster", "clearly", "hindi",
    "english", "hinglish", "speaker", "narrator", "presenter", "customer", "host", "guest", "variant", "picture",
    "ask", "voltage", "a", "an", "one", "two", "three", "four", "first", "second", "third", "last", "new", "more",
    "less", "calm", "unhurried", "narration", "offer", "brand", "price", "music", "crowd", "cheers", "welcome",
    "mr", "mrs", "ms", "ok", "okay", "yes", "no", "now", "then", "again", "here", "there", "when", "where", "what",
    "who", "how", "why", "man", "woman", "man's", "woman's", "voice-over", "commentary", "sunset", "sunrise", "beach",
}
_NAME = re.compile(r"\b([A-Z][\w'’&.-]*(?:\s+[A-Z][\w'’&.-]*)*)")
_NEXT = re.compile(r"\s*<next>(.*?)</next>\s*$", re.S)


@dataclass(frozen=True)
class Suggestion:
    label: str
    prompt: str
    kind: str
    grounded_in: str

    def as_dict(self) -> dict:
        return asdict(self)


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", s.lower())


_SENTENCE_START = re.compile(r"(?:^|[.!?:]\s+|[“\"]\s*)([A-Z][\w'’-]*)")


def names_in(text: str) -> list[str]:
    """Capitalised runs that read as names ("Bhaji Cam", "Goa", "Diwali").
    The first word of a sentence is a verb or the like ("Introduce", "Lower"),
    not a name, unless more capitalised words follow it."""
    starts = {m.start(1) for m in _SENTENCE_START.finditer(text)}
    out = []
    for m in _NAME.finditer(text):
        tokens = m.group(1).split()
        if m.start(1) in starts and len(tokens) == 1:
            continue
        words = [w for w in tokens if w.lower().strip(".'’") not in COMMON]
        if words:
            out.append(" ".join(words))
    return out


def grounded(text: str, sources: str) -> bool:
    """Every name in `text` appears in the sources (transcript, screen text, brief)."""
    hay = _norm(sources)
    return all(all(part in hay.split() for part in _norm(name).split()) for name in names_in(text))


def _short(label: str) -> str:
    label = " ".join(label.split())
    if len(label) <= MAX_LABEL:
        return label
    cut = label[:MAX_LABEL + 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut[:MAX_LABEL]


def clean(raw, sources: str) -> list[Suggestion]:
    """The chips that pass: grounded, short, one per kind, four at most."""
    out: list[Suggestion] = []
    seen: set[str] = set()
    for item in raw or ():
        if isinstance(item, Suggestion):
            item = item.as_dict()
        if not isinstance(item, dict):
            continue
        label = _short(str(item.get("label") or ""))
        prompt = " ".join(str(item.get("prompt") or label).split())
        kind = str(item.get("kind") or "").strip().lower()
        ground = str(item.get("grounded_in") or "").strip().lower()
        if not label or kind not in KINDS or ground not in GROUNDS or kind in seen:
            continue
        if not grounded(label, sources) or not grounded(prompt, sources):
            continue
        seen.add(kind)
        out.append(Suggestion(label, prompt, kind, ground))
        if len(out) == MAX_CHIPS:
            break
    return out


GENERIC_SPEECH = (
    Suggestion("Tighten the longest line", "Find the longest line and tighten it so it reads faster, keeping its meaning.", "fix", "words"),
    Suggestion("Change the wording of a line", "Suggest a clearer wording for the line that matters most, and voice it.", "change", "words"),
    Suggestion("Try another voice for line 1", "Voice line 1 again in a different voice so I can compare.", "voice", "words"),
    Suggestion("Export the video", "Export the video as it is now.", "finish", "time"),
)
GENERIC_SILENT = (
    Suggestion("Describe what the picture shows", "Write a short voice-over that describes what the picture shows, without naming any place you cannot see named.", "add", "frames"),
    Suggestion("A calm, unhurried narration", "Write and voice a calm, unhurried narration over the quiet stretch.", "voice", "frames"),
    Suggestion("Add a line at the start", "Add one short line at the start that sets the scene.", "change", "time"),
)


def fallback(has_speech: bool) -> list[Suggestion]:
    """Without Claude: a small generic set by clip type, nothing specific to any clip."""
    return list(GENERIC_SPEECH if has_speech else GENERIC_SILENT)


def split_reply(reply: str) -> tuple[str, list]:
    """Voltage's closing words without their `<next>` block, and the block's chips (raw)."""
    if not reply:
        return reply, []
    m = _NEXT.search(reply)
    if not m:
        return reply, []
    try:
        data = json.loads(m.group(1).strip())
    except (ValueError, TypeError):
        data = []
    return reply[: m.start()].rstrip(), data if isinstance(data, list) else []


PROMPT_RULES = """\
- Suggestions: end your closing message with a line `<next>` and a JSON \
list of two to four chips for what the user might do next, then `</next>`. \
Each chip is {"label", "prompt", "kind", "grounded_in"}. label: at most 40 \
characters, in the clip's language when obvious. prompt: what the user would \
say to you, more precise than the label. kind: fix (a mistake or unclear \
word), change (an offer, a wording), add (a new line or voice-over), voice \
(another voice or delivery) or finish (export, a variant); at most one per \
kind. grounded_in: time, words, frames or brief, for what the chip points \
at. Ground every chip in this video: a time ("Tighten the line at 0:12"), a \
word said, what the frames show, or the brief. Name a place, brand or person \
only if it is in the transcript, on screen or in the brief. When something \
needs the user, the chips are the ways out ("Shorten line 2", "Let the \
picture ease"). After you made something, refine it ("Make line 2 warmer", \
"Try a man's voice for line 1"). Offer finish chips (Export, a variant) once \
nothing is pending. The user never sees this block; it becomes the chips.\
"""
