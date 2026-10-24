"""The video as a piece (2026-10-20): the VideoUnderstanding record.

Built on the first read from the clip's signals (`media.understand`) and one
look by the model (genre, subjects, visual events, a style line). Stored
with the video, versioned, and editable: the user's corrections ("This is
Muay Thai", "That's not a knockdown, he slipped") are kept apart from
Voltage's own read and win over it in every later turn. The style line is
proposed by Voltage and the user's when accepted or changed.

Names are checked: a person, place, team, brand or sponsor appears only if
it is on screen, spoken, or in the brief. A field that names something
nobody said or showed loses that name before it is stored.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.agent.suggestions import grounded, names_in

FIELDS = ("format", "genre", "purpose", "audience", "setting", "subjects", "summary", "audio_notes", "language", "style_line")
GENRE_STYLES = {
    "sports clip": "Live commentary: present tense, punchy, reacting on the beats, rising with the energy.",
    "travel reel": "Warm, unhurried and sensory.",
    "ad": "The brief's brand tone, with the offer said clearly once.",
    "talking head": "Match the speaker, with minimal changes.",
    "tutorial": "Clear, calm, step by step.",
    "food": "Warm and sensory, close to the food.",
    "event": "Lively and present, naming only what is shown.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DESCRIPTIONS = {"setting", "subjects", "summary", "audio_notes"}
SAME_MOMENT_S = 0.35


def _strip_names(text: str, sources: str, strict: bool = True) -> str:
    """`text` without any sentence that names something not in the sources.
    Descriptions are read strictly; the style line, an instruction, is not."""
    if not text or grounded(text, sources, strict=strict):
        return text
    kept = [s for s in re.split(r"(?<=[.!?])\s+", text) if grounded(s, sources, strict=strict)]
    return " ".join(kept)


def build(signals: dict, vision: dict | None, sources: str, previous: dict | None = None) -> dict:
    """A new version of the record: the signals, the model's read (names
    checked against `sources`), and the corrections and style the user had."""
    prev = previous or {}
    seen = (vision or {})
    screen = " ".join(seen.get("on_screen_text") or [])
    allowed = f"{sources} {screen}"
    read = {k: _strip_names(str(seen.get(k) or ""), allowed, strict=k in DESCRIPTIONS) for k in FIELDS}
    events = [{"at": round(float(e["at"]), 2), "kind": "visual", "label": str(e["label"]).strip(),
               "confidence": round(float(e.get("confidence", 0.5)), 2), "source": "vision"}
              for e in seen.get("visual_events") or [] if grounded(str(e.get("label", "")), allowed, strict=True)]
    beats = sorted([*signals.get("beats", []), *events], key=lambda b: b["at"])
    style = prev.get("style") or {}
    if not style.get("accepted"):
        line = read["style_line"] or GENRE_STYLES.get(read["format"], "")
        style = {"line": line, "accepted": False, "by": "voltage", "shown": bool(style.get("shown"))}
    return {
        "version": int(prev.get("version") or 0) + 1,
        "at": _now(),
        "signals": signals,
        "read": {**read, "on_screen_text": list(seen.get("on_screen_text") or [])},
        "beats": beats,
        "corrections": list(prev.get("corrections") or []),
        "style": style,
    }


def correct(record: dict, text: str, beat_at: float | None = None, label: str | None = None, remove: bool = False) -> dict:
    """A user correction, kept with the record and applied over Voltage's read:
    free words ("This is Muay Thai"), or a beat relabelled or removed."""
    entry = {"text": text.strip(), "at": _now()}
    if beat_at is not None:
        entry["beat_at"] = round(float(beat_at), 2)
        if remove:
            entry["remove"] = True
        elif label:
            entry["label"] = label.strip()
    return {**record, "corrections": [*record.get("corrections", []), entry]}


def view(record: dict) -> dict:
    """The record as it stands with the user's corrections applied: the beats
    relabelled or removed, a genre the user named taking the place of Voltage's."""
    beats = [dict(b) for b in record.get("beats", [])]
    for c in record.get("corrections", []):
        if "beat_at" not in c:
            continue
        hit = min(beats, key=lambda b: abs(b["at"] - c["beat_at"]), default=None)
        if hit is None or abs(hit["at"] - c["beat_at"]) > 0.6:
            continue
        if c.get("remove"):
            beats.remove(hit)
        else:
            hit.update(label=c.get("label") or hit["label"], source="user", confidence=1.0)
    return {**record, "beats": beats}


def context_lines(record: dict | None) -> list[str]:
    """The understanding as Voltage reads it at the top of a turn. The user's
    corrections come first and are said to win."""
    if not record:
        return []
    v = view(record)
    read = v.get("read") or {}
    sig = v.get("signals") or {}
    out = []
    if v.get("corrections"):
        out.append("The user corrected your read of this video; these win over everything below: "
                   + " | ".join(c["text"] for c in v["corrections"] if c.get("text")))
    kind = ", ".join(x for x in (read.get("format"), read.get("genre")) if x)
    out.append(f"What you see: {kind or 'unknown'}, {sig.get('orientation', 'unknown')}"
               + (f"; {read['summary']}" if read.get("summary") else ""))
    if read.get("setting") or read.get("subjects"):
        out.append(f"Setting: {read.get('setting') or '?'}. Subjects: {read.get('subjects') or '?'}.")
    if read.get("on_screen_text"):
        out.append("On screen: " + "; ".join(f"“{t}”" for t in read["on_screen_text"]))
    # Cost 1e: a motion peak at the moment a named beat already marks says nothing more.
    named = [b["at"] for b in v.get("beats", []) if b.get("kind") == "visual" or b.get("source") == "user"]
    beats = [f"{b['at']:.1f} s {b['label']}" + (" (user)" if b.get("source") == "user" else "" if b.get("confidence", 0) >= 0.6 else " (unsure)")
             for b in v.get("beats", []) if b.get("kind") != "cut"
             and not (b.get("kind") == "motion" and any(abs(b["at"] - t) <= SAME_MOMENT_S for t in named))]
    cuts = [f"{b['at']:.1f}" for b in v.get("beats", []) if b.get("kind") == "cut"]
    if beats:
        out.append("Beats: " + "; ".join(beats) + ".")
    if cuts:
        out.append("Cuts at " + ", ".join(cuts) + " s.")
    energy = sig.get("energy") or []
    if energy:
        step = sig.get("energy_step", 0.5)
        hi = max(range(len(energy)), key=lambda k: energy[k])
        calm = [k for k, e in enumerate(energy) if e < 0.35]
        out.append(f"Energy peaks near {hi * step:.1f} s" + (f"; calm stretches at {', '.join(f'{k * step:.1f}' for k in calm[:4])} s" if calm else "") + ".")
    if read.get("audio_notes"):
        out.append(f"Sound already there: {read['audio_notes']}.")
    style = v.get("style") or {}
    if style.get("line"):
        out.append(f"Style for this video ({'accepted by the user' if style.get('accepted') else 'your proposal, not yet accepted'}): {style['line']}")
    return out
