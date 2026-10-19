"""The tools Voltage works through (Phase 20a). Each wraps something the
backend already does, typed for the model, with a guard class.

A tool gets the `Workbench` (the seams into the app) and the `Turn` (this
turn's project, plan, autonomy and caps) and returns a `ToolResult`: what the
model reads, what the thread shows as one step, and what it cost.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from app.agent.guards import Guard, TurnBudget, WaitingForUser
from app.domain.models import BACKGROUND_DB, Selection
from app.domain.plan import Plan, PlanItem


@dataclass(frozen=True)
class ToolResult:
    text: str                                   # what the model reads
    blocks: list[dict] | None = None            # instead of text: text + image blocks
    step: str | None = None                     # the line the thread shows; None = silent
    cost_usd: float = 0.0
    card: dict | None = None                    # {text, data}: a card the thread shows after the step (voice previews)
    data: dict | None = None                    # facts the step message carries (search_help: the articles found)


@dataclass
class Workbench:
    """The seams into the app a tool may use. Built once by the API from its
    own helpers; tests build one from fakes."""
    repo: Any
    ledger: Any
    frames: Callable[[Any], Sequence[Any]]                    # record -> [Frame(at, path)]
    lines: Callable[[Any], Sequence[Any]]                     # record -> [Line]
    room_after: Callable[[Any, Selection, float], float]      # transcript, selection, duration -> seconds
    voices: Callable[[], Sequence[dict]]
    library: Callable[..., Sequence[dict]]                    # (accent, language=) -> hits
    estimate_usd: Callable[[str], tuple[int, float]]          # text -> (characters, usd)
    generate: Callable[..., Any]                              # the app's _generate
    ensure_spend: Callable[[str], None]
    ship: Callable[..., dict]                                 # (project_id, record, plan_id, item_ids) -> approval dict
    default_voice: Callable[[], str]
    hear: Callable[[Any, float, float], dict] | None = None   # record, start, end -> {noise_db, speech_db}
    sight_text: Callable[[str], str] = lambda project_id: ""
    now: Callable[[], str] = lambda: ""
    # 20b: voices made for the clip. None = this setup cannot (no vendor).
    design: Callable[[str, str, str | None], Sequence[dict]] | None = None   # project_id, description, text -> previews
    design_cost: Callable[[str | None], tuple[int, float]] = lambda text=None: (0, 0.0)   # text -> (chars, usd)
    save_voice: Callable[[str, str, str], str] | None = None         # generated_voice_id, name, description -> voice_id
    add_from_library: Callable[[str, str, str], str] | None = None   # owner_id, voice_id, name -> voice_id
    delete_voice: Callable[[str], None] | None = None
    slots: Callable[[], tuple[int, int] | None] = lambda: None       # (used, limit) or unknown
    put_audio: Callable[[str, bytes, str, float], Any] | None = None  # project_id, bytes, container, duration -> artifact
    # 20c: speech clips. None = this setup cannot.
    speakers: Callable[[str], Sequence[Any]] = lambda project_id: []            # -> [Speaker(label, name, voice_id, clone_voice_id)]
    voice_for: Callable[..., Any] | None = None       # (project_id, record, selection, requested, speaker) -> VoiceChoice
    remove_words: Callable[[str, Any, Selection], dict] | None = None           # -> {edit_id, candidate_id, selection}
    shift_words: Callable[[str, Any, Selection, float], dict] | None = None     # -> {edit_id, removed_edit_id, candidate, from, selection}
    move_take: Callable[..., Any] | None = None       # (project_id, record, candidate, start, mix) -> candidate
    # 20e: what is in the video already, and taking one edit back out.
    edits: Callable[[str], Sequence[Any]] = lambda project_id: []         # -> live ApprovedEdit (not reverted)
    revert: Callable[[str, str], bool] | None = None                      # (project_id, edit_id) -> undone
    # 20i: the user's own uploaded voices, by owner.
    mine: Callable[[str], Sequence[dict]] = lambda owner: []
    # 20g: a line mixed louder or softer, nothing voiced again.
    relevel_take: Callable[[str, Any, float], Any] | None = None          # (project_id, candidate, level_db) -> candidate
    relevel_edit: Callable[[str, str, float], dict | None] | None = None  # (project_id, edit_id, level_db) -> {edit_id, reverted, candidate}
    # Folders: the project the video is in — {project_id, name, brief, voices: [entries], videos: [sisters], files: [{name, text}]} — or None.
    project: Callable[[str], dict | None] = lambda video_id: None
    # Bug 1: the final render against the edits as they are now — {edit_hash, render, at, rendering, edits}.
    render_state: Callable[[str], dict] = lambda video_id: {}
    # Folders: record a brief suggestion for the project page -> its id, or None when the video is in no project.
    suggest: Callable[[str, str, str], str | None] | None = None          # (video_id, addition, why)
    # Help: the articles, best match first -> [{slug, section, title, summary, body, tour}]
    help_search: Callable[[str], Sequence[dict]] = lambda query: []


@dataclass
class Turn:
    project_id: str
    record: Any
    plan_id: str
    autonomy: str                       # "ask" | "draft"
    spend_approved: bool                # the user said go to this turn's paid step
    budget: TurnBudget
    started_at: str                     # ISO time, for "spent this turn"
    report: Callable[[float, str], None] = lambda p, s: None
    progress: float = 0.0
    commit_approved: bool = False
    takes: list[str] = field(default_factory=list)
    # The steps the user chose to be asked about even under Just do it
    # (Settings): shipping, cloning a speaker, designing a voice.
    ask_before: dict = field(default_factory=lambda: {"ship": False, "clone": False, "design": False})

    def asks_before(self, what: str) -> bool:
        """Whether this committing step waits for the user: always under
        Check with me, and under Just do it when they asked for it in
        Settings; never once they have said yes this turn."""
        return not self.commit_approved and (self.autonomy == "ask" or bool(self.ask_before.get(what)))


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    guard: Guard
    run: Callable[[Workbench, Turn, dict], ToolResult]
    # Strict only where an argument can be got wrong in a way that matters
    # (enums, dials, arrays). The API compiles every strict schema into one
    # grammar and refuses when it grows too large ("The compiled grammar is
    # too large", seen live with 19 strict tools), so the simple ones — one
    # id, one number — are left plain.
    strict: bool = False

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema,
                "strict": self.strict and bool(self.schema.get("properties"))}


def _schema(properties: dict, required: Sequence[str] | None = None) -> dict:
    # Strict schemas: every property named in `required`, optional ones nullable.
    return {"type": "object", "properties": properties, "required": list(required or properties.keys()),
            "additionalProperties": False}


def _opt(t: str, description: str, **extra) -> dict:
    # The API caps union-typed parameters across all strict tools (a nullable
    # counts); so a string or array that may be empty is plain, with "" or []
    # meaning none, and only numbers that have no empty value are nullable.
    return {"type": [t, "null"], "description": description, **extra}


MAX_UNIONS = 8   # what the schemas may use between them; the API refused 18
MAX_STRICT = 8   # strict tools per request; the API refused 22 outright, and 19 as a grammar too large


# ── free: look and listen ─────────────────────────────────────────────────────

MAX_FRAMES = 6


def _look_at_frames(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    frames = list(wb.frames(turn.record))
    if not frames:
        return ToolResult("No frames could be read from this clip.", step="Tried to look; no frames")
    wanted = args.get("at") or []
    if wanted:
        picked = []
        for t in wanted[:MAX_FRAMES]:
            nearest = min(frames, key=lambda f: abs(f.at - float(t)))
            if nearest not in picked:
                picked.append(nearest)
    else:
        step = max(1, len(frames) // MAX_FRAMES)
        picked = frames[::step][:MAX_FRAMES]
    blocks: list[dict] = []
    for f in picked:
        data = base64.standard_b64encode(Path(f.path).read_bytes()).decode("ascii")
        blocks.append({"type": "text", "text": f"Frame at {f.at:.1f} s:"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    noted = wb.sight_text(turn.project_id)
    tail = f"The clip is {turn.record.source.duration:.1f} s long."
    if noted:
        tail += f" What you noted when you first looked: {noted}"
    blocks.append({"type": "text", "text": tail})
    return ToolResult("", blocks=blocks, step=f"Looked at {len(picked)} {'frame' if len(picked) == 1 else 'frames'}")


def _read_transcript(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    lines = list(wb.lines(turn.record))
    if not lines:
        return ToolResult(f"No one speaks in this clip. It is {turn.record.source.duration:.1f} s of picture and sound.",
                          step="Listened — no one speaks")
    out = ["Transcript (line. [start–end s] speaker: words  (syllables now, up to N fit in the slot)):"]
    labels = {s.name: s.label for s in wb.speakers(turn.project_id)}
    for ln in lines:
        who = f" {ln.speaker}:" if ln.speaker else ""
        fits = f"  ({ln.syllables} syl now, up to {ln.budget} fit)" if ln.syllables is not None and ln.budget is not None else ""
        out.append(f"{ln.index}. [{ln.start:.1f}–{ln.end:.1f}]{who} {ln.text}{fits}")
    spk = [s for s in wb.speakers(turn.project_id)]
    if spk:
        out.append("Speakers: " + "; ".join(f"{s.name} ({s.label})" + (" — own voice made" if s.clone_voice_id else "") for s in spk)
                   + ". A replacement in a speaker's line speaks in their own voice when voice_id is empty.")
    del labels
    return ToolResult("\n".join(out), step=f"Read all {len(lines)} {'line' if len(lines) == 1 else 'lines'}")


def _room(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    record = turn.record
    duration = record.source.duration
    lines = list(wb.lines(record))
    if not lines:
        return ToolResult(f"The whole clip is free: 0.0–{duration:.1f} s with no speech. A line placed here plays "
                          "over the picture and the sound. At a narration pace about 4 syllables fit each second.",
                          step="Found room: the whole clip")
    out = ["Room after each line (silence a new line could play over, in seconds):"]
    for ln in lines:
        room = wb.room_after(record.transcript, Selection(ln.start, ln.end), duration)
        out.append(f"- after line {ln.index} ({ln.end:.1f} s): {room:.1f} s")
    return ToolResult("\n".join(out), step="Found the pauses")


def _hear(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    start, end = float(args["start"]), float(args["end"])
    duration = turn.record.source.duration
    start, end = max(0.0, start), min(duration, end)
    if end <= start:
        return ToolResult("That span is empty.")
    words = [w for w in getattr(turn.record.transcript, "words", ()) if w.start < end and w.end > start]
    said = " ".join(w.text for w in words)
    facts = []
    if wb.hear is not None:
        try:
            levels = wb.hear(turn.record, start, end)
            if levels.get("noise_db") is not None:
                facts.append(f"background at {levels['noise_db']:.0f} dBFS")
            if levels.get("speech_db") is not None:
                facts.append(f"speech at {levels['speech_db']:.0f} dBFS")
        except Exception as exc:  # noqa: BLE001 — a listen that fails is said, not raised
            facts.append(f"could not measure the sound ({type(exc).__name__})")
    text = f"{start:.1f}–{end:.1f} s: " + (f"someone says “{said}”" if said else "no speech") + (
        f"; {', '.join(facts)}" if facts else "") + "."
    return ToolResult(text, step=f"Listened to {start:.1f}–{end:.1f} s")


def _list_voices(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    voices = list(wb.voices())
    if not voices:
        return ToolResult("No voices are available.", step="Looked for voices — none")
    made = {m["voice_id"]: m for m in _made_voices(wb, turn)}
    out = ["Voices that can speak a line (voice_id · name · who · how they sound):"]
    shared = _project_voices(wb, turn)
    for v in shared:
        # Folders: the project's voices first; one that carries consent needs no new consent here.
        out.append(f"- {v['voice_id']} · {v['name']} · in this project" + (f" · {v['description']}" if v.get("description") else "")
                   + (" · consent given" if v.get("consent") else ""))
    for v in voices:
        who = ", ".join(str(x).replace("_", " ") for x in (v.get("gender"), v.get("accent"), v.get("age")) if x)
        tag = ""
        if v["voice_id"] in made:
            tag = " · designed for this clip" if made[v["voice_id"]].get("kind") == "designed" else " · added from the library for this clip"
        out.append(f"- {v['voice_id']} · {v['name']}" + (f" · {who}" if who else "")
                   + (f" · {v['description']}" if v.get("description") else "") + tag)
    mine = list(wb.mine(getattr(turn.record, "owner", "")))
    if mine:
        out.append("The user's own voices (uploaded by them; \"my voice\" means one of these):")
        for v in mine:
            out.append(f"- {v['voice_id']} · {v['name']} · yours, {v.get('seconds', 0):.0f} s of reference")
    out.append(f"The default is {wb.default_voice()}. If none fits, search the library (add_voice_from_library) "
               "or design one from words (design_voice).")
    return ToolResult("\n".join(out), step=f"Looked through {len(voices) + len(mine) + len(shared)} voices")


def _project_voices(wb: Workbench, turn: Turn) -> list[dict]:
    project = wb.project(turn.project_id)
    return list((project or {}).get("voices") or [])


def _search_library(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    accent = (args.get("accent") or "").strip().lower() or None
    gender = (args.get("gender") or "").strip().lower() or None
    try:
        hits = list(wb.library(accent or "", language="en")) if accent else []
    except Exception as exc:  # noqa: BLE001
        return ToolResult(f"The voice library could not be searched ({exc}).", step="Searched the voice library — unavailable")
    if gender:
        hits = [h for h in hits if (h.get("gender") or "").lower() == gender]
    hits = hits[:8]
    if not hits:
        return ToolResult("Nothing in the library matched. Searching needs an accent "
                          "(indian, british, american, australian, …); the description narrows it in your own judgement.",
                          step="Searched the voice library — nothing")
    out = ["Library voices, most used first (name · who · how they sound · voice_id · owner_id). Not in the catalogue yet: "
           "add_voice_from_library puts one there (a voice slot, no credits); the description is yours to judge against:"]
    for h in hits:
        who = ", ".join(str(x).replace("_", " ") for x in (h.get("gender"), h.get("accent"), h.get("age")) if x)
        out.append(f"- {h['name']} · {who} · {h.get('description', '')[:120]} · {h['voice_id']} · {h.get('public_owner_id', '')}")
    return ToolResult("\n".join(out), step=f"Searched the voice library — {len(hits)} found")


def _estimate(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    chars, usd = wb.estimate_usd(args["text"])
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    return ToolResult(f"About {chars} voice characters, ${usd:.2f}. This turn has spent ${spent:.2f} of ${turn.budget.usd:.2f}.")


def _project_state(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    spent_turn = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    spent_all = wb.ledger.spent_usd(turn.project_id)
    out = [f"Autonomy: {'Check with me' if turn.autonomy == 'ask' else 'Just do it'}. "
           f"This turn: ${spent_turn:.2f} of ${turn.budget.usd:.2f}; the project: ${spent_all:.2f}."]
    items = [i for i in (plan.items if plan else ()) if i.kind == "planned" and i.status != "dismissed"]
    if not items:
        out.append("No lines planned or voiced yet.")
    for i in items:
        out.append(f"- {i.item_id} at {i.selection.start:.1f}–{i.selection.end:.1f} s: “{i.new_text}” — {i.status}"
                   + (f", take {i.candidate_id}" if i.candidate_id else ""))
    out.extend(shipped_lines(wb.edits(turn.project_id)))
    out.append(render_line(wb.render_state(turn.project_id)))
    return ToolResult("\n".join(out))


_MIX_WORDS = {"layer": "layered over the picture and sound", "over": "over the picture", "replace": "replacing the words",
              "concatenate": "added after the line, the picture holding", "remove": "the words removed"}


def render_line(state: dict) -> str:
    """The render, as the record has it — the only ground for saying the video is ready."""
    if not state:
        return "Render: unknown in this setup; do not say the video is rendered or ready."
    if not state.get("edits"):
        return "Render: nothing is in the video yet; the original plays."
    if state.get("render"):
        return f"Render: the final render matches the edits in the video now (finished {state.get('at') or 'earlier'})."
    if state.get("rendering"):
        return "Render: the final render for the edits now is still running; say it is rendering, not ready."
    return "Render: no finished render of the edits now; the video is rendered when the user opens it or exports. Do not say it is ready."


def shipped_lines(edits: Sequence[Any]) -> list[str]:
    """What is in the video already, one line per live edit, for the agent's
    view of the project (20e). Layered edits stack: two over the same span
    both play."""
    live = [e for e in edits if not getattr(e, "reverted", False)]
    if not live:
        return []
    out = ["In the video already (shipped; undo_edit takes one out):"]
    for e in live:
        sel = e.plan.selection
        words = f"“{e.plan.new_text}”" if e.plan.new_text else "(silence)"
        out.append(f"- {e.edit_id} at {sel.start:.1f}–{sel.end:.1f} s: {words} — {_MIX_WORDS.get(e.plan.mix, e.plan.mix)}")
    return out


# ── free: the project around the video (Folders), and Help ───────────────────

def _list_project_videos(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    project = wb.project(turn.project_id)
    if not project:
        return ToolResult("This video is in no project; it has no sister videos.", step="Looked for sister videos — none")
    sisters = list(project.get("videos") or [])
    if not sisters:
        return ToolResult(f"{project.get('name')} holds no other video yet.", step="Looked for sister videos — none")
    out = [f"The other videos in {project.get('name')} (read only — this turn changes only its own video):"]
    for v in sisters:
        shipped = list(v.get("shipped") or [])
        said = "; ".join(f"“{e.get('text')}”" + (f" in {e['voice']}" if e.get("voice") else "") for e in shipped if e.get("text"))
        out.append(f"- {v.get('filename')} ({float(v.get('duration') or 0):.1f} s, {v.get('state', 'new')}): "
                   + (f"shipped {said}" if said else "nothing shipped yet"))
    return ToolResult("\n".join(out), step=f"Read the {len(sisters)} sister {'video' if len(sisters) == 1 else 'videos'}")


MAX_PASSAGES = 6
PASSAGE_CHARS = 240


def passages_of(files: Sequence[dict], query: str, limit: int = MAX_PASSAGES, width: int = PASSAGE_CHARS) -> list[tuple[str, str]]:
    """Passages of the files' text around the query's words, with the file
    name: the whole query first, then any of its words."""
    words = [w for w in re.findall(r"[\w'-]+", query.lower()) if len(w) > 2]
    needles = [query.strip().lower()] + words if query.strip() else words
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, int]] = set()
    for needle in needles:
        if not needle:
            continue
        for f in files:
            text = f.get("text") or ""
            lowered = text.lower()
            at = lowered.find(needle)
            while at != -1 and len(out) < limit:
                start = max(0, at - width // 2)
                key = (f.get("name", ""), start // width)
                if key not in seen:
                    seen.add(key)
                    piece = " ".join(text[start:start + width].split())
                    out.append((f.get("name", ""), ("…" if start else "") + piece + ("…" if start + width < len(text) else "")))
                at = lowered.find(needle, at + len(needle))
            if len(out) >= limit:
                return out
    return out


def _read_project_files(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    project = wb.project(turn.project_id)
    if not project:
        return ToolResult("This video is in no project; there are no reference files.", step="Looked for reference files — none")
    files = list(project.get("files") or [])
    if not files:
        return ToolResult(f"{project.get('name')} has no reference files yet.", step="Looked for reference files — none")
    query = (args.get("query") or "").strip()
    unread = [f["name"] for f in files if not (f.get("text") or "").strip()]
    if not query:
        return ToolResult("The reference files: " + ", ".join(f["name"] for f in files) + ". Say what to look for."
                          + (f" No text could be read from {', '.join(unread)}." if unread else ""), step="Listed the reference files")
    found = passages_of(files, query)
    if not found:
        return ToolResult(f"Nothing in the reference files mentions “{query}”. The files: " + ", ".join(f["name"] for f in files) + "."
                          + (f" No text could be read from {', '.join(unread)}." if unread else ""),
                          step=f"Searched the reference files for “{query[:40]}” — nothing")
    out = [f"Passages about “{query}” (file · passage):"]
    out.extend(f"- {name} · {piece}" for name, piece in found)
    return ToolResult("\n".join(out), step=f"Searched the reference files for “{query[:40]}” — {len(found)} found")


def _suggest_brief(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    addition = (args.get("addition") or "").strip()
    why = (args.get("why") or "").strip()
    if not addition:
        return ToolResult("Say what the brief should add.")
    if wb.suggest is None or not wb.project(turn.project_id):
        return ToolResult("This video is in no project, so there is no brief to add to.")
    sid = wb.suggest(turn.project_id, addition, why)
    if sid is None:
        return ToolResult("This video is in no project, so there is no brief to add to.")
    return ToolResult(f"Suggested for the brief ({sid}): “{addition}”. The brief changes only when the user accepts it on the project page.",
                      step=f"Suggested for the brief: “{addition[:48]}{'…' if len(addition) > 48 else ''}”")


HELP_EXCERPT = 600


def _search_help(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult("Say what to look for in Help.")
    try:
        hits = list(wb.help_search(query))[:3]
    except Exception as exc:  # noqa: BLE001 — Help that cannot be read is said, not raised
        return ToolResult(f"Help could not be searched ({exc}).", step="Looked in Help — unavailable")
    if not hits:
        return ToolResult(f"Help has no article about “{query}”. Say so rather than guess at a feature.",
                          step=f"Looked in Help for “{query[:40]}” — nothing")
    out = [f"Help articles about “{query}” (name the one you answer from):"]
    for h in hits:
        body = " ".join((h.get("body") or "").split())
        excerpt = body[:HELP_EXCERPT] + ("…" if len(body) > HELP_EXCERPT else "")
        out.append(f"- {h.get('slug')} · {h.get('section')} / {h.get('title')}" + (f" · {h['summary']}" if h.get("summary") else "")
                   + (f" · shows the user: {h['tour']}" if h.get("tour") else "") + f"\n  {excerpt}")
    data = {"help": [{"slug": h.get("slug"), "title": h.get("title"), "section": h.get("section"), "tour": h.get("tour")} for h in hits]}
    return ToolResult("\n".join(out), step=f"Looked in Help: {hits[0].get('title')}", data=data)


# ── spend: a take ─────────────────────────────────────────────────────────────

# Free-text direction → the vendor settings the adapter knows (20b replaces
# this with the model's own mapping to settings and audio tags).
_DIRECTION_WORDS = (
    ("more excited", ("excited", "energetic", "lively", "upbeat", "bright", "enthusiastic")),
    ("calmer", ("calm", "gentle", "soft", "unhurried", "wistful", "slow", "quiet", "soothing", "tender")),
    ("warmer", ("warm", "friendly", "kind", "smile")),
    ("firmer", ("firm", "confident", "strong", "assured", "serious")),
)


def delivery_of(direction: str | None) -> str | None:
    if not direction:
        return None
    lowered = direction.lower()
    for key, words in _DIRECTION_WORDS:
        if any(w in lowered for w in words):
            return key
    return direction


def _voice_name(wb: Workbench, voice_id: str, turn: Turn | None = None) -> str:
    mine = wb.mine(getattr(turn.record, "owner", "")) if turn is not None else ()
    shared = _project_voices(wb, turn) if turn is not None else ()
    return next((v["name"] for v in [*wb.voices(), *mine, *shared] if v["voice_id"] == voice_id), voice_id)


# An audio tag in the words: "[sighs]", "[whispers]", "[long pause]".
_TAG = re.compile(r"\[[^\[\]\n]{1,40}\]")
MODELS = ("v2", "v3", "v4")
_SETTING_KEYS = {"stability": "stability", "style": "style", "speed": "speed", "similarity": "similarity_boost"}


def voice_settings_of(args: dict | None) -> dict | None:
    """The model's dials as the vendor names them, read from the tool's own
    arguments; None when none were set."""
    out = {_SETTING_KEYS[k]: float(v) for k, v in (args or {}).items() if k in _SETTING_KEYS and v is not None}
    return out or None


def model_for(text: str, wanted: str | None) -> str | None:
    """The vendor model short name for a take: the one asked for, else v4
    when the words carry audio tags (a model that reads tags as words would
    say them), else None for the default."""
    wanted = (wanted or "").strip().lower() or None
    if wanted in MODELS:
        return wanted
    return "v4" if _TAG.search(text) else None


def _made_voices(wb: Workbench, turn: Turn) -> list[dict]:
    return list(wb.repo.settings(turn.project_id).get("made_voices") or [])


def _remember_voice(wb: Workbench, turn: Turn, voice_id: str, name: str, kind: str, description: str | None = None) -> None:
    made = [m for m in _made_voices(wb, turn) if m["voice_id"] != voice_id]
    made.append({"voice_id": voice_id, "name": name, "kind": kind, "at": wb.now(), "description": description})
    wb.repo.set_settings(turn.project_id, made_voices=made)


def _slots_line(wb: Workbench) -> str:
    slots = wb.slots()
    if not slots:
        return ""
    used, limit = slots
    return f" {used} of {limit} voice slots are used" + (" — nearly full; delete a voice before making more." if limit - used <= 5 else ".")


def _plan(wb: Workbench, turn: Turn) -> Plan:
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    if plan is None:
        raise RuntimeError("the turn's plan is gone")
    return plan


def _synthesize_take(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    text = (args.get("text") or "").strip().strip('"').strip("“”")
    if not text:
        return ToolResult("There are no words to voice.")
    voice_id = (args.get("voice_id") or "").strip()
    own = voice_id in ("", "own")          # the speaker's own voice when the line has a speaker, else the default
    known = [*wb.voices(), *wb.mine(getattr(turn.record, "owner", "")), *_project_voices(wb, turn)]
    if not own and voice_id != wb.default_voice() and not any(v["voice_id"] == voice_id for v in known):
        return ToolResult(f"{voice_id} is not a voice in the catalogue. Use list_voices and pick one of its ids, "
                          "or leave it empty for the speaker's own voice.")
    duration = turn.record.source.duration
    record = turn.record
    lines = list(wb.lines(record))
    line_no = args.get("line")
    item_id = args.get("item_id")
    plan = _plan(wb, turn)
    existing = plan.item(item_id) if item_id else None

    moved = False
    if existing is not None:
        selection, old_text, mix, speaker = existing.selection, existing.old_text, existing.mix, existing.speaker
        # A placed line voiced again with a new span moves to it.
        if old_text == "" and args.get("start") is not None and args.get("end") is not None:
            start, end = max(0.0, float(args["start"])), min(duration, float(args["end"]))
            if end <= start:
                return ToolResult(f"That span is empty; the clip is {duration:.1f} s long.")
            moved = (round(start, 2), round(end, 2)) != (selection.start, selection.end)
            selection = Selection(round(start, 2), round(end, 2))
            if args.get("mix") in ("layer", "concatenate"):
                mix = args["mix"]
    elif line_no:
        line = next((ln for ln in lines if ln.index == int(line_no)), None)
        if line is None:
            return ToolResult(f"There is no line {line_no}. The transcript has {len(lines)}.")
        selection, old_text, mix = Selection(line.start, line.end), line.text, "replace"
        st = next((s for s in _statements(record) if abs(s.start - line.start) < 0.01), None)
        speaker = st.speaker if st else None
    else:
        start, end = args.get("start"), args.get("end")
        if start is None or end is None:
            return ToolResult("A placed line needs start and end (seconds); a replacement needs the line number.")
        start, end = max(0.0, float(start)), min(duration, float(end))
        if end <= start:
            return ToolResult(f"That span is empty; the clip is {duration:.1f} s long.")
        selection, old_text, speaker = Selection(round(start, 2), round(end, 2)), "", None
        mix = "concatenate" if args.get("mix") == "concatenate" else "layer"

    chars, usd = wb.estimate_usd(text)
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    refusal = turn.budget.refuses(spent, usd)
    if refusal:
        return ToolResult(refusal)
    who = _speaker_name(wb, turn, speaker) if speaker else None
    if own:
        whose = f"{who}'s own voice" if who and wb.voice_for is not None else f"{_voice_name(wb, wb.default_voice())}'s voice"
    else:
        whose = f"{_voice_name(wb, voice_id, turn)}'s voice"
    if turn.autonomy == "ask" and not turn.spend_approved:
        raise WaitingForUser(f"Voice “{text}” in {whose}, about ${usd:.2f}?", cost_usd=usd)
    wb.ensure_spend(turn.project_id)
    voice_notes: tuple[str, ...] = ()
    if own:
        voice_id = wb.default_voice()
        if who and wb.voice_for is not None:
            # Picked for them on purpose, else their clone (made now from their own speech), else the default.
            choice = wb.voice_for(turn.project_id, record, selection, wb.default_voice(), speaker)
            voice_id, voice_notes = choice.voice_id, tuple(choice.notes)
            whose = f"{who}'s own voice" if choice.cloned else f"{_voice_name(wb, voice_id)}'s voice"
    name = whose[:-len("'s voice")] if whose.endswith("'s voice") else whose
    fit = {"natural": "start", "stretch": "stretch"}.get(args.get("fit") or "fit")
    picture = args.get("picture") or "default"
    flex_max = 1.0 if picture == "as shot" or (picture == "default" and old_text == "") else None

    direction = (args.get("direction") or "").strip() or None
    delivery = delivery_of(direction)
    settings = voice_settings_of(args)
    model = model_for(text, args.get("model"))
    level_db = BACKGROUND_DB if args.get("level") == "background" else None
    if existing is None:
        item = PlanItem(item_id=f"i{len(plan.items) + 1}", selection=selection, old_text=old_text, new_text=text,
                        speaker=speaker, mix=mix, delivery=delivery, reason=direction or "", kind="planned",
                        enabled=True, status="working")
        wb.repo.update_plan(turn.project_id, turn.plan_id, items=plan.items + (item,))
    else:
        item = existing
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="working", new_text=text,
                            delivery=delivery, reason=direction or "", error=None, selection=selection, mix=mix)

    def step(progress: float, what: str) -> None:
        turn.report(turn.progress, what)
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, progress=what)

    before = wb.ledger.spent_usd(turn.project_id)
    candidate_id = wb.repo.next_candidate_id(turn.project_id)
    try:
        # One take per call (the adapter's takes-by-duration aside): a take that
        # fails the sound check comes back with its report, and the retry — with
        # a different direction, voice or wording — is Voltage's own call.
        candidate = wb.generate(turn.project_id, record, candidate_id, selection, text, voice_id,
                                fit, mix, step, delivery=delivery, voice_notes=voice_notes,
                                voice_settings=settings, model=model, flex_max=flex_max, max_regenerations=0,
                                level_db=level_db)
    except Exception as exc:  # noqa: BLE001 — the model hears why and decides; nothing crashes the turn
        reason = str(exc) or type(exc).__name__
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="failed", error=reason, progress=None)
        return ToolResult(f"The take could not be made: {reason}", step=f"Could not voice “{text[:40]}” — {reason[:80]}")
    cost = max(0.0, wb.ledger.spent_usd(turn.project_id) - before)
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="ready", candidate_id=candidate.candidate_id,
                        progress=None, error=None, fit=candidate.plan.fit)
    turn.takes.append(candidate.candidate_id)
    report = candidate.continuity
    verdict = "sounds right" if report.passed else "did not pass the sound check" + (
        f": {'; '.join(report.warnings)}" if report.warnings else "")
    took = candidate.plan.selection
    notes = f" Fit: {', '.join(candidate.fit_notes)}." if candidate.fit_notes else ""
    wps = ""
    if candidate.words:
        secs = max(0.1, candidate.words[-1].end - candidate.words[0].start)
        wps = f" The take itself runs {secs:.1f} s, {len(candidate.words) / secs:.1f} words a second."
    where = (f"placed at {took.start:.2f} s, over the picture" if item.old_text == "" and mix == "layer"
             else f"at {took.start:.2f}–{took.end:.2f} s ({took.end - took.start:.2f} s slot)")
    how_said = f" Spoken with {model or 'the default model'}" + (
        f", {', '.join(f'{k} {v:g}' for k, v in settings.items())}" if settings else "") + "."
    if voice_notes:
        how_said += " " + " ".join(voice_notes)
    text_out = (f"Take {candidate.candidate_id} on {item.item_id}, {whose}, {where}. It {verdict}.{notes}{wps}{how_said} "
                f"Cost ${cost:.2f}.{' The item moved to the new span.' if moved else ''} "
                f"The user can hear it now; voice it again (same item_id) to try another direction or wording, "
                f"or with a new start and end to move it.")
    how = f" — {direction}" if direction else ""
    return ToolResult(text_out, step=f"Voiced “{text[:48]}{'…' if len(text) > 48 else ''}” with {name}{how}", cost_usd=cost)


def _statements(record) -> list:
    from app.domain.transcript import statements_of
    return list(statements_of(record.transcript))


def _keep_take(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = _plan(wb, turn)
    item = plan.item(args["item_id"])
    if item is None:
        return ToolResult(f"There is no item {args['item_id']}.")
    candidate = wb.repo.get_candidate(turn.project_id, args["candidate_id"])
    if candidate is None:
        return ToolResult(f"There is no take {args['candidate_id']}.")
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="ready", candidate_id=candidate.candidate_id,
                        new_text=candidate.plan.new_text)
    return ToolResult(f"{item.item_id} now carries take {candidate.candidate_id}.", step=f"Kept take {candidate.candidate_id} on {item.item_id}")


def _drop_item(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = _plan(wb, turn)
    item = plan.item(args["item_id"])
    if item is None:
        return ToolResult(f"There is no item {args['item_id']}.")
    if item.status == "approved":
        return ToolResult(f"{item.item_id} is in the video; undo_edit takes it out.")
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="dismissed", enabled=False)
    return ToolResult(f"{item.item_id} is dropped.", step=f"Dropped {item.item_id} (“{item.new_text[:40]}”)")


def _design_voice(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.design is None or wb.put_audio is None:
        return ToolResult("Voices cannot be designed in this setup; pick from list_voices.")
    description = (args.get("description") or "").strip()
    if not description:
        return ToolResult("Describe the voice in words first.")
    sample = (args.get("sample_text") or "").strip() or None
    if sample and len(sample) < 100:
        return ToolResult("A sample text needs at least 100 characters; leave it null and the vendor writes one that shows the voice off.")
    chars, usd = wb.design_cost(sample)
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    refusal = turn.budget.refuses(spent, usd)
    if refusal:
        return ToolResult(refusal)
    # A paid step: waits under Check with me like a take, and under Just do it
    # when the user asked to be asked before a voice is designed.
    if (turn.autonomy == "ask" and not turn.spend_approved) or (turn.ask_before.get("design") and not turn.commit_approved):
        raise WaitingForUser(f"Design a voice from “{description}” — three previews to hear, about ${usd:.2f}?", cost_usd=usd)
    wb.ensure_spend(turn.project_id)
    turn.report(turn.progress, "Designing a voice")
    before = wb.ledger.spent_usd(turn.project_id)
    try:
        previews = list(wb.design(turn.project_id, description, sample))
    except Exception as exc:  # noqa: BLE001 — the model hears why
        reason = str(exc) or type(exc).__name__
        return ToolResult(f"The voice could not be designed: {reason}", step=f"Could not design a voice — {reason[:80]}")
    cost = max(0.0, wb.ledger.spent_usd(turn.project_id) - before)
    if not previews:
        return ToolResult("The vendor sent no previews back.", step="Designed a voice — nothing came back", cost_usd=cost)
    designs = dict(wb.repo.settings(turn.project_id).get("designs") or {})
    rows = []
    for n, pv in enumerate(previews, 1):
        container = "wav" if "wav" in (pv.get("media_type") or "") else "mp3"
        art = wb.put_audio(turn.project_id, pv["audio"], container, float(pv.get("duration") or 0.0))
        designs[pv["generated_voice_id"]] = {"description": description, "sha256": art.sha256,
                                             "duration": float(pv.get("duration") or 0.0), "n": n, "at": wb.now()}
        rows.append({"n": n, "generated_voice_id": pv["generated_voice_id"], "sha256": art.sha256,
                     "duration": round(float(pv.get("duration") or 0.0), 1)})
    wb.repo.set_settings(turn.project_id, designs=designs)
    card = {"text": f"{len(rows)} voices designed from “{description}”", "data": {"description": description, "previews": rows}}
    sample_len = len(previews[0].get("text") or "")
    ids = "; ".join(f"preview {r['n']}: {r['generated_voice_id']} ({r['duration']:.0f} s)" for r in rows)
    text_out = (f"{len(rows)} previews of a voice for “{description}”, each reading the same sample"
                f"{f' ({sample_len} characters)' if sample_len else ''}: {ids}. The user can play them in the thread now. "
                "You cannot hear them and they differ in ways only an ear tells, so either ask the user which one, or keep one "
                "with save_voice and say that you picked without hearing. A kept voice is named for the clip (two words at most) "
                f"and takes a voice slot.{_slots_line(wb)} Cost ${cost:.2f}.")
    return ToolResult(text_out, step=f"Designed a voice from “{description[:56]}{'…' if len(description) > 56 else ''}” — {len(rows)} previews to hear",
                      cost_usd=cost, card=card)


def _save_voice(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.save_voice is None:
        return ToolResult("Voices cannot be saved in this setup.")
    gid = (args.get("generated_voice_id") or "").strip()
    name = " ".join((args.get("name") or "").split())[:40]
    designs = wb.repo.settings(turn.project_id).get("designs") or {}
    if gid not in designs:
        return ToolResult(f"{gid or 'that'} is not a preview of this project; design_voice gives the ids.")
    if not name:
        return ToolResult("Give the voice a name (for the clip, two words at most).")
    try:
        voice_id = wb.save_voice(gid, name, designs[gid]["description"])
    except Exception as exc:  # noqa: BLE001
        reason = str(exc) or type(exc).__name__
        return ToolResult(f"The voice could not be saved: {reason}", step=f"Could not keep the voice — {reason[:80]}")
    _remember_voice(wb, turn, voice_id, name, "designed", description=designs[gid]["description"])
    n = designs[gid].get("n")
    return ToolResult(f"Saved preview {n} as “{name}” ({voice_id}); it is in the catalogue now and can speak a line.{_slots_line(wb)}",
                      step=f"Kept preview {n} as “{name}”")


def _add_from_library(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.add_from_library is None:
        return ToolResult("Library voices cannot be added in this setup.")
    owner, vid = (args.get("owner_id") or "").strip(), (args.get("voice_id") or "").strip()
    name = " ".join((args.get("name") or "").split())[:40]
    if not (owner and vid and name):
        return ToolResult("Adding needs the voice_id and owner_id from search_voice_library, and a name.")
    try:
        added = wb.add_from_library(owner, vid, name)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc) or type(exc).__name__
        return ToolResult(f"The voice could not be added: {reason}", step=f"Could not add {name} — {reason[:80]}")
    _remember_voice(wb, turn, added, name, "library")
    return ToolResult(f"{name} ({added}) is in the catalogue now and can speak a line.{_slots_line(wb)}",
                      step=f"Added {name} from the voice library")


def _delete_voice(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.delete_voice is None:
        return ToolResult("Voices cannot be deleted in this setup.")
    vid = (args.get("voice_id") or "").strip()
    mine = next((m for m in _made_voices(wb, turn) if m["voice_id"] == vid), None)
    if mine is None:
        return ToolResult(f"{vid or 'That'} is not a voice made for this clip; only those can be deleted here.")
    if not turn.commit_approved:
        raise WaitingForUser(f"Delete the voice “{mine['name']}” from the account?", ("Delete it", "Keep it"), "Delete it")
    try:
        wb.delete_voice(vid)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc) or type(exc).__name__
        return ToolResult(f"The voice could not be deleted: {reason}")
    wb.repo.set_settings(turn.project_id, made_voices=[m for m in _made_voices(wb, turn) if m["voice_id"] != vid])
    return ToolResult(f"“{mine['name']}” is deleted.{_slots_line(wb)}", step=f"Deleted the voice “{mine['name']}”")


def _speaker_name(wb: Workbench, turn: Turn, label: str | None) -> str | None:
    if not label:
        return None
    return next((s.name for s in wb.speakers(turn.project_id) if s.label == label), label)


def _speaker_label(wb: Workbench, turn: Turn, wanted: str) -> Any:
    wanted = (wanted or "").strip().lower()
    return next((s for s in wb.speakers(turn.project_id) if wanted in (s.label.lower(), s.name.lower())), None)


def _line_at(wb: Workbench, turn: Turn, line_no: Any):
    try:
        n = int(line_no)
    except (TypeError, ValueError):
        return None
    return next((ln for ln in wb.lines(turn.record) if ln.index == n), None)


def _clone_speaker(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.voice_for is None:
        return ToolResult("Voices cannot be cloned in this setup.")
    spk = _speaker_label(wb, turn, args.get("speaker") or "")
    if spk is None:
        names = ", ".join(f"{s.name} ({s.label})" for s in wb.speakers(turn.project_id)) or "none"
        return ToolResult(f"There is no speaker called {args.get('speaker')!r}. The speakers are: {names}.")
    if spk.clone_voice_id and not spk.voice_id:
        return ToolResult(f"{spk.name}'s own voice is already made ({spk.clone_voice_id}); a replacement in their line uses it when voice_id is empty.")
    picked = f" {_voice_name(wb, spk.voice_id)} was picked for them by hand; their own voice replaces it." if spk.voice_id else ""
    if turn.asks_before("clone"):
        raise WaitingForUser(f"Clone {spk.name}'s voice from their own speech in this clip? It stays with this project and goes when the project does.{picked}",
                             ("Clone it", "Not yet"), "Clone it")
    turn.report(turn.progress, f"Cloning {spk.name}'s voice")
    record = turn.record
    if spk.voice_id:
        # A voice picked by hand wins over a clone (15a); the user asked for their own, so the pick goes.
        wb.repo.set_speaker(turn.project_id, spk.label, clear_voice=True)
    choice = wb.voice_for(turn.project_id, record, Selection(0.0, record.source.duration), wb.default_voice(), spk.label)
    if choice.cloned:
        return ToolResult(f"{spk.name}'s own voice is made ({choice.voice_id}). A replacement in their line speaks in it when voice_id is empty.",
                          step=f"Cloned {spk.name}'s voice from their own speech")
    why = " ".join(choice.notes) or "The vendor did not make one."
    return ToolResult(f"{spk.name}'s voice could not be cloned. {why}", step=f"Could not clone {spk.name}'s voice")


def _remove_line(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.remove_words is None:
        return ToolResult("Lines cannot be removed in this setup.")
    line = _line_at(wb, turn, args.get("line"))
    if line is None:
        return ToolResult(f"There is no line {args.get('line')}.")
    out = wb.remove_words(turn.project_id, turn.record, Selection(line.start, line.end))
    sel = out["selection"]
    return ToolResult(f"Line {line.index} is proposed removed ({sel['start']:.2f}–{sel['end']:.2f} s; item {out['item_id']}): the room's own "
                      "sound in its place. Nothing is paid. Ship makes it part of the video.",
                      step=f"Proposed removing line {line.index} (“{line.text[:40]}”)")


def _shift_line(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.shift_words is None:
        return ToolResult("Lines cannot be moved in this setup.")
    line = _line_at(wb, turn, args.get("line"))
    if line is None:
        return ToolResult(f"There is no line {args.get('line')}.")
    to = float(args.get("to") or 0.0)
    if turn.autonomy == "ask" and not turn.commit_approved:
        raise WaitingForUser(f"Move line {line.index} (“{line.text}”) to {to:.2f} s, as spoken?", ("Move it", "Not yet"), "Move it")
    out = wb.shift_words(turn.project_id, turn.record, Selection(line.start, line.end), to)
    sel = out["selection"]
    return ToolResult(f"Line {line.index} now plays from {sel['start']:.2f} s (edit {out['edit_id']}); the room's sound is where it was. "
                      "It is part of the video already; undo_edit takes it out.",
                      step=f"Moved line {line.index} to {sel['start']:.2f} s")


def _move_item(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.move_take is None:
        return ToolResult("Takes cannot be moved in this setup.")
    plan = _plan(wb, turn)
    item = plan.item((args.get("item_id") or "").strip())
    if item is None or not item.candidate_id:
        return ToolResult(f"There is no voiced item {args.get('item_id')}.")
    if item.status == "approved":
        return ToolResult(f"{item.item_id} is in the video; the user can move it from its row.")
    candidate = wb.repo.get_candidate(turn.project_id, item.candidate_id)
    if candidate is None:
        return ToolResult(f"The take {item.candidate_id} is gone.")
    start = max(0.0, float(args.get("start") or 0.0))
    moved = wb.move_take(turn.project_id, turn.record, candidate, start, None)
    sel = moved.plan.selection
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, candidate_id=moved.candidate_id,
                        selection=Selection(sel.start, sel.end))
    return ToolResult(f"{item.item_id} now plays at {sel.start:.2f}–{sel.end:.2f} s as take {moved.candidate_id} (the same audio, not voiced again).",
                      step=f"Moved {item.item_id} to {sel.start:.2f} s")


def _set_level(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    """20g: a line mixed under the words (background) or at full level (foreground), nothing voiced again."""
    level_db = BACKGROUND_DB if args.get("level") == "background" else 0.0
    word = "background" if level_db else "foreground"
    item_id, edit_id = (args.get("item_id") or "").strip(), (args.get("edit_id") or "").strip()
    if item_id:
        if wb.relevel_take is None:
            return ToolResult("Levels cannot be set in this setup.")
        plan = _plan(wb, turn)
        item = plan.item(item_id)
        if item is None or not item.candidate_id:
            return ToolResult(f"There is no voiced item {item_id}.")
        if item.status == "approved":
            return ToolResult(f"{item_id} is in the video; name its edit (edit_id) instead — project_state lists them.")
        candidate = wb.repo.get_candidate(turn.project_id, item.candidate_id)
        if candidate is None:
            return ToolResult(f"The take {item.candidate_id} is gone.")
        out = wb.relevel_take(turn.project_id, candidate, level_db)
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, candidate_id=out.candidate_id)
        return ToolResult(f"{item_id} is {word} now ({level_db:+.0f} dB), as take {out.candidate_id}; the same audio, not voiced again.",
                          step=f"Set {item_id} to {word}")
    if edit_id:
        if wb.relevel_edit is None:
            return ToolResult("Levels cannot be set in this setup.")
        if turn.autonomy == "ask" and not turn.commit_approved:
            raise WaitingForUser(f"Mix {edit_id} as {word} ({level_db:+.0f} dB)?", ("Yes", "Not yet"), "Yes")
        out = wb.relevel_edit(turn.project_id, edit_id, level_db)
        if out is None:
            return ToolResult(f"There is no live edit {edit_id}; project_state lists what is in the video.")
        return ToolResult(f"{edit_id} is {word} now ({level_db:+.0f} dB) as edit {out['edit_id']}; the video is rendered again when something ships next.",
                          step=f"Set {edit_id} to {word}")
    return ToolResult("Name an item_id (a proposal) or an edit_id (a line in the video).")


def _measure(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    c = wb.repo.get_candidate(turn.project_id, (args.get("candidate_id") or "").strip())
    if c is None:
        return ToolResult(f"There is no take {args.get('candidate_id')}.")
    r = c.continuity
    scores = []
    for label, key, value in (("prosody", "prosody", r.prosody), ("audio integration", "audio_integration", r.audio_integration),
                              ("voice match", "voice_match", r.voice_match), ("naturalness", "naturalness", r.naturalness)):
        if value is not None:
            scores.append(f"{label} {value:.2f}" + (" of 5" if key == "naturalness" else "") + ("" if key in r.measured else " (estimated)"))
    out = [f"Take {c.candidate_id}: {'passed' if r.passed else 'did not pass'} the sound check" + (f" — {'; '.join(scores)}" if scores else "") + "."]
    out.append(f"Runs {c.audio.duration:.2f} s" + (
        f"; {len(c.words)} words, {len(c.words) / max(0.1, c.words[-1].end - c.words[0].start):.1f} a second" if c.words else "") + ".")
    if c.fit_notes:
        out.append(f"Fit: {', '.join(c.fit_notes)}.")
    if r.warnings:
        out.append("Warnings: " + " ".join(r.warnings))
    out.append(f"Spoken with {c.plan.model or 'the default model'}" + (
        f", {', '.join(f'{k} {v:g}' for k, v in c.plan.voice_settings.items())}" if c.plan.voice_settings else "") + ".")
    return ToolResult(" ".join(out))


# ── commit ────────────────────────────────────────────────────────────────────

def _ship(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = _plan(wb, turn)
    wanted = args.get("item_ids") or None
    ready = [i for i in plan.items if i.kind == "planned" and i.status == "ready" and (not wanted or i.item_id in wanted)]
    if not ready:
        return ToolResult("Nothing is ready to ship: no voiced line that is not already shipped.")
    n = len(ready)
    anyway = bool(args.get("anyway"))
    if turn.asks_before("ship"):
        raise WaitingForUser(f"Ship {n} {'change' if n == 1 else 'changes'} and render the video?"
                             + (" One did not pass its check." if anyway else ""), ("Ship it", "Not yet"), "Ship it")
    result = wb.ship(turn.project_id, turn.record, turn.plan_id, [i.item_id for i in ready], override=anyway)
    shipped = len(result.get("approved", []))
    skipped = result.get("skipped", [])
    flagged = [s for s in skipped if s.get("reason") == "continuity check failed"]
    text = f"Shipped {shipped} {'change' if shipped == 1 else 'changes'}" + (
        f"; {len(skipped)} skipped ({'; '.join(s['reason'] for s in skipped)})" if skipped else "") + "."
    if flagged:
        text += (" A take that did not pass its check ships only on the user's word: when they say ship it as it is, "
                 "call ship again with anyway set, and say the check flagged it.")
    state = wb.render_state(turn.project_id)
    if result.get("export") and state.get("render"):
        text += " The edited video is rendered for these edits; the user can download it from the top bar."
    elif shipped:
        text += " The render for these edits has not finished; do not say the video is ready."
    return ToolResult(text, step=text.split(" A take that")[0].rstrip("."))


def _undo_edit(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    if wb.revert is None:
        return ToolResult("Edits cannot be undone in this setup; the user can, with Take it out on the line.")
    edit_id = (args.get("edit_id") or "").strip()
    edit = next((e for e in wb.edits(turn.project_id) if e.edit_id == edit_id and not getattr(e, "reverted", False)), None)
    if edit is None:
        return ToolResult(f"There is no live edit {edit_id or '(none)'}; project_state lists what is in the video.")
    words = edit.plan.new_text or "the removal"
    if turn.autonomy == "ask" and not turn.commit_approved:
        raise WaitingForUser(f"Take {edit_id} (“{words}”) back out of the video?", ("Undo it", "Keep it"), "Undo it")
    if not wb.revert(turn.project_id, edit_id):
        return ToolResult(f"{edit_id} could not be undone.")
    return ToolResult(f"{edit_id} is undone: the video no longer carries “{words}”. The render is remade when something ships next.",
                      step=f"Undid {edit_id} (“{words[:40]}”)")


def _ask(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    options = tuple(o.strip() for o in (args.get("options") or []) if o and o.strip())[:3]
    if len(options) < 2:
        return ToolResult("Give two or three options to choose from.")
    raise WaitingForUser(args["question"].strip(), options, (args.get("guess") or "").strip() or None, gate=False)


# ── the registry ──────────────────────────────────────────────────────────────

TOOLS: tuple[Tool, ...] = (
    Tool("look_at_frames", "Look at the picture: up to six frames of the clip as images, evenly spaced, or the ones nearest the times you name.",
         _schema({"at": {"type": "array", "items": {"type": "number"}, "description": "Times in seconds to look at; empty for an even spread."}}), Guard.FREE, _look_at_frames),
    Tool("read_transcript", "Read every spoken line with who says it, when, and how many syllables its slot can hold. Says so when no one speaks.",
         _schema({}), Guard.FREE, _read_transcript),
    Tool("find_room", "Where a new line can go: the whole clip when there is no speech, else the pause after each line.",
         _schema({}), Guard.FREE, _room),
    Tool("hear", "Listen to a span: whether anyone speaks there and what they say, and how loud the background and the speech are.",
         _schema({"start": {"type": "number", "description": "Seconds."}, "end": {"type": "number", "description": "Seconds."}}), Guard.FREE, _hear),
    Tool("list_voices", "The voices a line can be spoken in: id, name, gender, accent, age, how they sound.",
         _schema({}), Guard.FREE, _list_voices),
    Tool("search_voice_library", "Look beyond the catalogue in the vendor's voice library, by accent (required) and gender; add one with add_voice_from_library.",
         _schema({"description": {"type": "string", "description": "The kind of voice wanted, in words."},
                  "accent": {"type": "string", "description": "indian, british, american, australian, …"},
                  "gender": {"type": "string", "description": "female, male, or empty for either."}}), Guard.FREE, _search_library, strict=True),

    Tool("estimate", "What voicing these words would cost, and what this turn has left.",
         _schema({"text": {"type": "string", "description": "The words."}}), Guard.FREE, _estimate),
    Tool("project_state", "Where things stand: the plan's items and their states, and the money.",
         _schema({}), Guard.FREE, _project_state),
    Tool("list_project_videos", "The other videos in this video's project (Folders): each one's name, length, state, and the lines and voices it shipped. Read only; a turn changes only its own video.",
         _schema({}), Guard.FREE, _list_project_videos),
    Tool("read_project_files", "Search the project's reference files (a brief, a script, notes) for a word or phrase; returns the matching passages with the file name. Empty lists the files.",
         _schema({"query": {"type": "string", "description": "What to look for; empty to list the files."}}), Guard.FREE, _read_project_files),
    Tool("suggest_brief", "Suggest something the project's brief should say, with why. Recorded for the project page; the brief changes only when the user accepts it.",
         _schema({"addition": {"type": "string", "description": "The sentence or two to add."},
                  "why": {"type": "string", "description": "Why, in a few words."}}), Guard.FREE, _suggest_brief),
    Tool("search_help", "Look up how Voltage works in the help articles: up to three with slug, title, section, summary, an excerpt and what the tour can show. Answer how-do-I questions from these, naming the article; never guess at a feature.",
         _schema({"query": {"type": "string", "description": "The question, in the user's words."}}), Guard.FREE, _search_help),
    Tool("synthesize_take",
         "Voice a line and place it, as a take the user can hear. Costs money (see estimate). Either replace a transcript line (give `line`) "
         "or place new words by time (give `start` and `end`; `mix` layer = over the picture and sound, concatenate = the picture waits). "
         "To try again on the same item, give its `item_id`. How it is said is yours: `direction` in words (kept with the take), "
         "`settings` as the vendor's dials, and for v3/v4 audio tags inside `text` — [sighs], [laughs], [whispers], [exhales], "
         "[long pause], [excited], [sad], [curious]; an ellipsis for a held beat, CAPITALS for weight. "
         "Models: v4 (the vendor's newest; the most emotive, performs tags, keeps the sentence around a seam), v3 (expressive, performs tags, "
         "but a replacement inside someone's sentence loses that context), v2 (the steadiest, finest style control, reads a tag as words so tags are stripped). "
         "Null picks the default, v4 when the text carries tags.",
         _schema({"text": {"type": "string", "description": "The spoken words only; no name or label in front. Audio tags in square brackets are allowed."},
                  "voice_id": {"type": "string", "description": "A voice_id from list_voices; empty for the speaker's own voice (a replacement) or the default (a placed line)."},
                  "direction": {"type": "string", "description": "How to say it, in your words: e.g. warm and unhurried, a half-smile; brisk and confident. Empty for none."},
                  "model": {"type": "string", "enum": ["default", "v2", "v3", "v4"], "description": "Which model speaks it."},
                  "stability": _opt("number", "0 varied and emotional … 1 steady and even; v3/v4 read 0, 0.5, 1 as creative, natural, robust. Null leaves it alone."),
                  "style": _opt("number", "0 plain … 1 exaggerated (v2 mostly). Null leaves it alone."),
                  "speed": _opt("number", "0.7 slow … 1.2 brisk; 1 is natural. Null leaves it alone."),
                  "similarity": _opt("number", "0 … 1, how closely the voice's own timbre is held. Null leaves it alone."),
                  "line": _opt("integer", "The transcript line to replace, when replacing; else null."),
                  "start": _opt("number", "Seconds, when placing new words; else null."),
                  "end": _opt("number", "Seconds, when placing new words; else null."),
                  "mix": {"type": "string", "enum": ["layer", "concatenate"], "description": "When placing: layer = over the picture and sound (the usual), concatenate = the picture waits."},
                  "fit": {"type": "string", "enum": ["fit", "natural", "stretch"], "description": "How the take meets its slot: fit = pauses first, then tempo (the usual); natural = as spoken from the slot's start, running into the pause; stretch = tempo only."},
                  "picture": {"type": "string", "enum": ["default", "as shot", "may flex"], "description": "Whether the picture under the take may run a little slower or faster to fit it. default = as shot for a placed line, may flex for a replacement."},
                  "level": {"type": "string", "enum": ["foreground", "background"], "description": "foreground = full level (words). background = mixed 12 dB under, for cheers, a crowd, ambience, anything that plays under other words so both are heard."},
                  "item_id": {"type": "string", "description": "An existing item to voice again; empty for a new one."}}), Guard.SPEND, _synthesize_take, strict=True),
    Tool("keep_take", "Put an earlier take back on an item (after voicing it again and preferring the first).",
         _schema({"item_id": {"type": "string"}, "candidate_id": {"type": "string"}}), Guard.FREE, _keep_take),
    Tool("drop_item", "Drop a planned or voiced line from the plan (not one that has shipped).",
         _schema({"item_id": {"type": "string"}}), Guard.FREE, _drop_item),
    Tool("design_voice",
         "Make a voice from words when the catalogue has nothing that fits: three previews the user can hear (about 25 s each, the same sample text), "
         "for the price of the sample text (the vendor's own is about 350 characters). Keep one with save_voice. Costs money.",
         _schema({"description": {"type": "string", "description": "Who is speaking: age, gender, accent, texture, manner — e.g. an Indian woman near fifty, unhurried, a smile in the voice, slight rasp."},
                  "sample_text": {"type": "string", "description": "What the previews read, 100 characters or more; empty lets the vendor write one."}}),

         Guard.SPEND, _design_voice, strict=True),
    Tool("save_voice", "Keep one preview from design_voice as a voice of the catalogue, named for the clip. Takes a voice slot, no credits.",
         _schema({"generated_voice_id": {"type": "string", "description": "A preview id from design_voice."},
                  "name": {"type": "string", "description": "A name for the clip, two words at most."}}), Guard.COMMIT, _save_voice),
    Tool("add_voice_from_library", "Put a library voice (from search_voice_library) in the catalogue so it can speak a line. Takes a voice slot, no credits.",
         _schema({"voice_id": {"type": "string"}, "owner_id": {"type": "string"},
                  "name": {"type": "string", "description": "The name to list it under."}}), Guard.COMMIT, _add_from_library),
    Tool("delete_voice", "Remove a voice Voltage made for this clip (designed or added from the library) from the account. Always asks the user first.",
         _schema({"voice_id": {"type": "string"}}), Guard.COMMIT, _delete_voice),
    Tool("clone_speaker", "Make a speaker's own voice from their speech in this clip, so their lines can be replaced in it. Takes a slot; asks first under Check with me. "
         "A replacement with an empty voice_id does this on its own.",
         _schema({"speaker": {"type": "string", "description": "The speaker's name or label, from read_transcript."}}), Guard.COMMIT, _clone_speaker, strict=True),
    Tool("remove_line", "Propose taking a spoken line out: the words go, the room's own sound stays, the picture is untouched. A proposal like a take; ship makes it part of the video.",
         _schema({"line": {"type": "integer", "description": "The transcript line."}}), Guard.FREE, _remove_line),
    Tool("shift_line", "Move a spoken line to another time, as it was spoken: nothing is voiced. Part of the video at once (undo from the review).",
         _schema({"line": {"type": "integer"}, "to": {"type": "number", "description": "Where the words should start, in seconds."}}), Guard.COMMIT, _shift_line, strict=True),
    Tool("move_item", "Place a voiced item's take at another time, the same audio, nothing voiced again.",
         _schema({"item_id": {"type": "string"}, "start": {"type": "number", "description": "Seconds."}}), Guard.FREE, _move_item),
    Tool("set_level", "Mix a line louder or softer without voicing it again: background (12 dB under the words) or foreground. A proposal by item_id, or a line in the video by edit_id.",
         _schema({"item_id": {"type": "string", "description": "A proposal; empty when naming an edit."},
                  "edit_id": {"type": "string", "description": "A line in the video; empty when naming an item."},
                  "level": {"type": "string", "enum": ["foreground", "background"]}}), Guard.COMMIT, _set_level),
    Tool("measure", "The full sound check of a take: its scores, what was done to fit it, how it was spoken.",
         _schema({"candidate_id": {"type": "string"}}), Guard.FREE, _measure),
    Tool("ship", "Make the voiced lines part of the video and render it. Only when the user asks for it, or said just do it and the work is done.",
         _schema({"item_ids": {"type": "array", "items": {"type": "string"}, "description": "Which items; empty for every voiced line."},
                  "anyway": {"type": "boolean", "description": "Ship a take that did not pass its check. Only when the user said to ship it as it is."}}),

         Guard.COMMIT, _ship, strict=True),
    Tool("undo_edit", "Take a shipped edit back out of the video (project_state lists them). A redo of a line that is in the video already: voice the new take, ship it, then undo the old edit, so lines do not pile up.",
         _schema({"edit_id": {"type": "string"}}), Guard.COMMIT, _undo_edit),
    Tool("ask", "Stop and ask the user one thing, with two or three options and your own guess. The turn ends; their answer starts the next.",
         _schema({"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                  "guess": {"type": "string", "description": "The option you would take; empty for none."}}), Guard.FREE, _ask, strict=True),

)

BY_NAME = {t.name: t for t in TOOLS}


def strict_count() -> int:
    return sum(1 for t in TOOLS if t.definition()["strict"])


def union_count() -> int:
    """How many parameters across the tools are union-typed (the API's cap)."""
    n = 0
    for t in TOOLS:
        for prop in t.schema["properties"].values():
            if isinstance(prop.get("type"), list) or "anyOf" in prop:
                n += 1
    return n


def definitions() -> list[dict]:
    return [t.definition() for t in TOOLS]
