"""The tools Voltage works through (Phase 20a). Each wraps something the
backend already does, typed for the model, with a guard class.

A tool gets the `Workbench` (the seams into the app) and the `Turn` (this
turn's project, plan, autonomy and caps) and returns a `ToolResult`: what the
model reads, what the thread shows as one step, and what it cost.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from app.agent.guards import Guard, TurnBudget, WaitingForUser
from app.domain.models import Selection
from app.domain.plan import Plan, PlanItem


@dataclass(frozen=True)
class ToolResult:
    text: str                                   # what the model reads
    blocks: list[dict] | None = None            # instead of text: text + image blocks
    step: str | None = None                     # the line the thread shows; None = silent
    cost_usd: float = 0.0


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


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    guard: Guard
    run: Callable[[Workbench, Turn, dict], ToolResult]

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema, "strict": True}


def _schema(properties: dict, required: Sequence[str] | None = None) -> dict:
    # Strict schemas: every property named in `required`, optional ones nullable.
    return {"type": "object", "properties": properties, "required": list(required or properties.keys()),
            "additionalProperties": False}


def _opt(t: str, description: str, **extra) -> dict:
    return {"type": [t, "null"], "description": description, **extra}


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
    for ln in lines:
        who = f" {ln.speaker}:" if ln.speaker else ""
        fits = f"  ({ln.syllables} syl now, up to {ln.budget} fit)" if ln.syllables is not None and ln.budget is not None else ""
        out.append(f"{ln.index}. [{ln.start:.1f}–{ln.end:.1f}]{who} {ln.text}{fits}")
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
    out = ["Voices that can speak a line (voice_id · name · who · how they sound):"]
    for v in voices:
        who = ", ".join(str(x).replace("_", " ") for x in (v.get("gender"), v.get("accent"), v.get("age")) if x)
        out.append(f"- {v['voice_id']} · {v['name']}" + (f" · {who}" if who else "")
                   + (f" · {v['description']}" if v.get("description") else ""))
    out.append(f"The default is {wb.default_voice()}.")
    return ToolResult("\n".join(out), step=f"Looked through {len(voices)} voices")


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
    out = [f"Library voices (not in the catalogue yet; adding one takes a voice slot — in this version say so and use the closest catalogue voice):"]
    for h in hits:
        who = ", ".join(str(x).replace("_", " ") for x in (h.get("gender"), h.get("accent"), h.get("age")) if x)
        out.append(f"- {h['name']} · {who} · {h.get('description', '')[:120]}")
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
    return ToolResult("\n".join(out))


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


def _voice_name(wb: Workbench, voice_id: str) -> str:
    return next((v["name"] for v in wb.voices() if v["voice_id"] == voice_id), voice_id)


def _plan(wb: Workbench, turn: Turn) -> Plan:
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    if plan is None:
        raise RuntimeError("the turn's plan is gone")
    return plan


def _synthesize_take(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    text = (args.get("text") or "").strip().strip('"').strip("“”")
    if not text:
        return ToolResult("There are no words to voice.")
    voice_id = (args.get("voice_id") or "").strip() or wb.default_voice()
    if voice_id != wb.default_voice() and not any(v["voice_id"] == voice_id for v in wb.voices()):
        return ToolResult(f"{voice_id} is not a voice in the catalogue. Use list_voices and pick one of its ids.")
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
    name = _voice_name(wb, voice_id)
    if turn.autonomy == "ask" and not turn.spend_approved:
        raise WaitingForUser(f"Voice “{text}” with {name}'s voice, about ${usd:.2f}?")
    wb.ensure_spend(turn.project_id)

    direction = (args.get("direction") or "").strip() or None
    delivery = delivery_of(direction)
    if existing is None:
        item = PlanItem(item_id=f"i{len(plan.items) + 1}", selection=selection, old_text=old_text, new_text=text,
                        speaker=speaker, mix=mix, delivery=delivery, reason=direction or "", kind="planned",
                        enabled=True, status="working")
        wb.repo.update_plan(turn.project_id, turn.plan_id, items=plan.items + (item,))
    else:
        item = existing
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="working", new_text=text,
                            delivery=delivery, error=None, selection=selection, mix=mix)

    def step(progress: float, what: str) -> None:
        turn.report(turn.progress, what)
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, progress=what)

    before = wb.ledger.spent_usd(turn.project_id)
    candidate_id = wb.repo.next_candidate_id(turn.project_id)
    try:
        candidate = wb.generate(turn.project_id, record, candidate_id, selection, text, voice_id,
                                None, mix, None, step, delivery=delivery, voice_notes=())
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
    text_out = (f"Take {candidate.candidate_id} on {item.item_id}, {name}'s voice, {where}. It {verdict}.{notes}{wps} "
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
        return ToolResult(f"{item.item_id} has shipped; the user can undo it from the review.")
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="dismissed", enabled=False)
    return ToolResult(f"{item.item_id} is dropped.", step=f"Dropped {item.item_id} (“{item.new_text[:40]}”)")


# ── commit ────────────────────────────────────────────────────────────────────

def _ship(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = _plan(wb, turn)
    wanted = args.get("item_ids") or None
    ready = [i for i in plan.items if i.kind == "planned" and i.status == "ready" and (not wanted or i.item_id in wanted)]
    if not ready:
        return ToolResult("Nothing is ready to ship: no voiced line that is not already shipped.")
    n = len(ready)
    if turn.autonomy == "ask" and not turn.commit_approved:
        raise WaitingForUser(f"Ship {n} {'change' if n == 1 else 'changes'} and render the video?", ("Ship it", "Not yet"), "Ship it")
    result = wb.ship(turn.project_id, turn.record, turn.plan_id, [i.item_id for i in ready])
    shipped = len(result.get("approved", []))
    skipped = result.get("skipped", [])
    text = f"Shipped {shipped} {'change' if shipped == 1 else 'changes'}" + (
        f"; {len(skipped)} skipped ({'; '.join(s['reason'] for s in skipped)})" if skipped else "") + "."
    if result.get("export"):
        text += " The edited video is rendered; the user can download it from the top bar."
    return ToolResult(text, step=text.rstrip("."))


def _ask(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    options = tuple(o.strip() for o in (args.get("options") or []) if o and o.strip())[:3]
    if len(options) < 2:
        return ToolResult("Give two or three options to choose from.")
    raise WaitingForUser(args["question"].strip(), options, (args.get("guess") or "").strip() or None, gate=False)


# ── the registry ──────────────────────────────────────────────────────────────

TOOLS: tuple[Tool, ...] = (
    Tool("look_at_frames", "Look at the picture: up to six frames of the clip as images, evenly spaced, or the ones nearest the times you name.",
         _schema({"at": _opt("array", "Times in seconds to look at; null for an even spread.", items={"type": "number"})}), Guard.FREE, _look_at_frames),
    Tool("read_transcript", "Read every spoken line with who says it, when, and how many syllables its slot can hold. Says so when no one speaks.",
         _schema({}), Guard.FREE, _read_transcript),
    Tool("find_room", "Where a new line can go: the whole clip when there is no speech, else the pause after each line.",
         _schema({}), Guard.FREE, _room),
    Tool("hear", "Listen to a span: whether anyone speaks there and what they say, and how loud the background and the speech are.",
         _schema({"start": {"type": "number", "description": "Seconds."}, "end": {"type": "number", "description": "Seconds."}}), Guard.FREE, _hear),
    Tool("list_voices", "The voices a line can be spoken in: id, name, gender, accent, age, how they sound.",
         _schema({}), Guard.FREE, _list_voices),
    Tool("search_voice_library", "Look beyond the catalogue in the vendor's voice library, by accent (required) and gender. Read-only in this version: nothing is added.",
         _schema({"description": {"type": "string", "description": "The kind of voice wanted, in words."},
                  "accent": _opt("string", "indian, british, american, australian, …"),
                  "gender": _opt("string", "female or male")}), Guard.FREE, _search_library),
    Tool("estimate", "What voicing these words would cost, and what this turn has left.",
         _schema({"text": {"type": "string", "description": "The words."}}), Guard.FREE, _estimate),
    Tool("project_state", "Where things stand: the plan's items and their states, and the money.",
         _schema({}), Guard.FREE, _project_state),
    Tool("synthesize_take",
         "Voice a line and place it, as a take the user can hear. Costs money (see estimate). Either replace a transcript line (give `line`) "
         "or place new words by time (give `start` and `end`; `mix` layer = over the picture and sound, concatenate = the picture waits). "
         "To try again on the same item, give its `item_id`. `direction` is how it should be said, in your words.",
         _schema({"text": {"type": "string", "description": "The spoken words only; no name or label in front."},
                  "voice_id": {"type": "string", "description": "A voice_id from list_voices."},
                  "direction": _opt("string", "How to say it: e.g. warm and unhurried, a half-smile; brisk and confident."),
                  "line": _opt("integer", "The transcript line to replace, when replacing."),
                  "start": _opt("number", "Seconds, when placing new words."),
                  "end": _opt("number", "Seconds, when placing new words."),
                  "mix": {"anyOf": [{"type": "string", "enum": ["layer", "concatenate"]}, {"type": "null"}],
                          "description": "layer (default) or concatenate, when placing."},
                  "item_id": _opt("string", "An existing item to voice again.")}), Guard.SPEND, _synthesize_take),
    Tool("keep_take", "Put an earlier take back on an item (after voicing it again and preferring the first).",
         _schema({"item_id": {"type": "string"}, "candidate_id": {"type": "string"}}), Guard.FREE, _keep_take),
    Tool("drop_item", "Drop a planned or voiced line from the plan (not one that has shipped).",
         _schema({"item_id": {"type": "string"}}), Guard.FREE, _drop_item),
    Tool("ship", "Make the voiced lines part of the video and render it. Only when the user asks for it, or said just do it and the work is done.",
         _schema({"item_ids": _opt("array", "Which items; null for every voiced line.", items={"type": "string"})}), Guard.COMMIT, _ship),
    Tool("ask", "Stop and ask the user one thing, with two or three options and your own guess. The turn ends; their answer starts the next.",
         _schema({"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                  "guess": _opt("string", "The option you would take.")}), Guard.FREE, _ask),
)

BY_NAME = {t.name: t for t in TOOLS}


def definitions() -> list[dict]:
    return [t.definition() for t in TOOLS]
