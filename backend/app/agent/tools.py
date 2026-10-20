"""The tools Voltage works through (Phase 20a). Each wraps something the
backend already does, typed for the model, with a guard class.

A tool gets the `Workbench` (the seams into the app) and the `Turn` (this
turn's project, plan, autonomy and caps) and returns a `ToolResult`: what the
model reads, what the thread shows as one step, and what it cost.
"""
from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from app.agent.guards import Guard, TurnBudget, WaitingForUser
from app.domain.models import ROLES, Selection, role_of
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
    rerole_take: Callable[[str, Any, str, float], Any] | None = None          # (project_id, candidate, role, offset_db) -> candidate
    rerole_edit: Callable[[str, str, str, float], dict | None] | None = None  # (project_id, edit_id, role, offset_db) -> {edit_id, reverted, candidate}
    only_voice: Callable[[str, Any, tuple], bool] | None = None             # (project_id, plan, skip ids) -> no other speech in its span
    # Folders: the project the video is in — {project_id, name, brief, voices: [entries], videos: [sisters], files: [{name, text}]} — or None.
    project: Callable[[str], dict | None] = lambda video_id: None
    # Bug 1: the final render against the edits as they are now — {edit_hash, render, at, rendering, edits}.
    render_state: Callable[[str], dict] = lambda video_id: {}
    # Folders: record a brief suggestion for the project page -> its id, or None when the video is in no project.
    suggest: Callable[[str, str, str], str | None] | None = None          # (video_id, addition, why)
    # Help: the articles, best match first -> [{slug, section, title, summary, body, tour}]
    help_search: Callable[[str], Sequence[dict]] = lambda query: []
    # Spend scopes: the one summary for a video ({turn?, video, project?, month, binding}) -> or None.
    spend: Callable[[str], dict | None] = lambda video_id: None
    # 2026-10-20 (p61): the last take's own spoken length before any fitting,
    # {seconds, speed}, for the voice's measured rate; None when unknown (a mock).
    measured: Callable[[], dict | None] = lambda: None
    # The same call as `generate`, but only from a take already paid for and
    # held (one that did not fit): never calls the vendor. None when the take
    # is not held; raises SpanMismatch when it still does not fit.
    held_take: Callable[..., Any] | None = None
    # 2026-10-20 (one processing model): every line voiced is a Job the editor
    # can show; None in a setup without them (the agent tests).
    jobs: Any = None


class NoJobs:
    """The job hooks when there are none: every call is a no-op."""

    def claim(self, project_id: str, item_id: str, **kw) -> str | None:
        return None

    def begin(self, project_id: str, kind: str, label: str, **kw) -> str | None:
        return None

    def step(self, job_id: str | None, label: str, progress: float | None = None) -> None:
        return None

    def settle(self, job_id: str | None, **kw) -> None:
        return None


NO_JOBS = NoJobs()


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
    # 2026-10-20 (p61): the lines that ran long this turn ({item_id: facts}),
    # the ones voiced again since, and whether Voltage was told to finish them.
    fit_failed: dict = field(default_factory=dict)
    fit_retried: set = field(default_factory=set)
    fit_nudged: bool = False
    # 2026-10-20: the user pressed Stop; the turn ends after the step that is running.
    stop_requested: Callable[[], bool] = lambda: False
    # A3: what the user said this turn; a banned word they typed themselves only warns.
    said: str = ""
    # F4: one video of a batch turn: its lines wait as proposals, added from the batch board.
    batch: bool = False

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
                          step="Listened: no one speaks")
    out = ["Transcript (line. [start–end s] speaker: words  (syllables now, up to N fit in the slot)):"]
    labels = {s.name: s.label for s in wb.speakers(turn.project_id)}
    for ln in lines:
        who = f" {ln.speaker}:" if ln.speaker else ""
        fits = f"  ({ln.syllables} syl now, up to {ln.budget} fit)" if ln.syllables is not None and ln.budget is not None else ""
        out.append(f"{ln.index}. [{ln.start:.1f}–{ln.end:.1f}]{who} {ln.text}{fits}")
    spk = [s for s in wb.speakers(turn.project_id)]
    if spk:
        out.append("Speakers: " + "; ".join(f"{s.name} ({s.label})" + (", own voice made" if s.clone_voice_id else "") for s in spk)
                   + ". A replacement in a speaker's line speaks in their own voice when voice_id is empty.")
    del labels
    return ToolResult("\n".join(out), step=f"Read all {len(lines)} {'line' if len(lines) == 1 else 'lines'}")


def _pace(wb: Workbench, turn: Turn, voice_id: str) -> tuple[str, float, int]:
    """(the voice's id, its measured rate, how many takes measured it): the default voice when none is named."""
    from app.agent import fitting
    vid = (voice_id or "").strip() or wb.default_voice()
    rate, takes = fitting.voice_rate(wb.repo, vid)
    return vid, rate, takes


def _room(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    from app.agent import fitting
    from app.media import fit as fitmod
    record = turn.record
    duration = record.source.duration
    lines = list(wb.lines(record))
    vid, rate, takes = _pace(wb, turn, args.get("voice_id") or "")
    pace = fitting.rate_words(_voice_name(wb, vid, turn), rate, takes) + "."
    if not lines:
        marks = fitting.beats(wb.repo.settings(turn.project_id))
        out = [f"The whole clip is free: 0.0–{duration:.1f} s with no speech. A line placed here plays over the picture and the sound. {pace}",
               "Placement windows (each runs to the next beat; a line's budget is the syllables its window holds at that rate, "
               f"less a {fitmod.LINE_GAP:.1f} s breath before the next line):"]
        for start, end, label in fitting.windows(duration, marks):
            room = max(0.0, end - start - (fitmod.LINE_GAP if end < duration - 1e-6 else 0.0))
            out.append(f"- {start:.1f}–{end:.1f} s ({end - start:.1f} s): up to {fitmod.syllables_for(room, rate)} syllables"
                       + (f"; beat: {label}" if label else ""))
        out.append(f"Commentary or narration: keep the talk under about {fitmod.COMMENTARY_SHARE:.0%} of the clip "
                   f"({duration * fitmod.COMMENTARY_SHARE:.1f} s here), so the lines breathe. Writing several lines? "
                   "plan_lines checks them together before anything is voiced.")
        return ToolResult("\n".join(out), step="Found room: the whole clip")
    out = [f"Room after each line (silence a new line could play over, in seconds, and the syllables it holds). {pace}"]
    for ln in lines:
        room = wb.room_after(record.transcript, Selection(ln.start, ln.end), duration)
        out.append(f"- after line {ln.index} ({ln.end:.1f} s): {room:.1f} s"
                   + (f", up to {fitmod.syllables_for(room, rate)} syllables" if room >= 0.3 else ""))
    return ToolResult("\n".join(out), step="Found the pauses")


def _plan_lines(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    """Several added lines, planned together before any is voiced (p61)."""
    from app.agent import fitting
    from app.media import fit as fitmod
    wanted = [ln for ln in (args.get("lines") or []) if isinstance(ln, dict)]
    if not wanted:
        return ToolResult("Give the lines: each one's start (seconds), its words (or empty to get a budget), and its end or -1.")
    vid, rate, takes = _pace(wb, turn, args.get("voice_id") or "")
    speed = float(args.get("speed") or 1.0) or 1.0
    duration = turn.record.source.duration
    out_plan = fitting.plan(wanted, duration, rate, speed, commentary=bool(args.get("commentary")))
    out = [f"{len(out_plan['lines'])} lines over {duration:.1f} s. {fitting.rate_words(_voice_name(wb, vid, turn), rate, takes)}"
           + (f", at speed {speed:g}" if abs(speed - 1) > 1e-6 else "") + "."]
    long = 0
    planned = _plan_rows(wb, turn, out_plan["lines"])
    for n, r in enumerate(out_plan["lines"], 1):
        head = f"{n}. {r['start']:.1f}–{r['end']:.1f} s, a {r['window']:.1f} s window: up to {r['budget']} syllables"
        if r["estimate"] is None:
            out.append(head + ".")
        elif r["fits"]:
            out.append(head + f"; “{r['text']}” runs about {r['estimate']:.1f} s ({r['syllables']} syllables). Fits."
                       + (f" Planned as {planned[n - 1]}." if planned.get(n - 1) else ""))
        else:
            long += 1
            out.append(head + f"; “{r['text']}” runs about {r['estimate']:.1f} s ({r['syllables']} syllables). Too long: "
                       f"rewrite to about {r['budget']} syllables.")
    if out_plan["breathing"]:
        out.append(f"The budgets hold the talk to about {fitmod.COMMENTARY_SHARE:.0%} of the clip, so the lines breathe.")
    out.append(f"Talk: about {out_plan['talk']:.1f} s, {out_plan['share']:.0%} of the clip.")
    if out_plan["over"]:
        out.append(f"For commentary that is too much: keep it under about {out_plan['limit']:.1f} s "
                   f"({fitmod.COMMENTARY_SHARE:.0%}). Cut a line or shorten several, so they breathe.")
    out.append("Write each line to its budget, then voice them. synthesize_take refuses a line it estimates too long, before paying."
               + (" Voice a planned line with its item_id." if planned else ""))
    step = f"Planned {len(out_plan['lines'])} lines together" + (f": {long} too long, to rewrite" if long else ": each fits its window")
    return ToolResult("\n".join(out), step=step)


def _plan_rows(wb: Workbench, turn: Turn, rows: Sequence[dict]) -> dict[int, str]:
    """Lines planned with their words, that fit, stand in the plan as items
    before any is voiced (2026-10-20): the user sees each row, and their Go
    queues every one at once. A line planned again at the same start keeps its
    item. Returns {row index: item id}."""
    plan = _plan(wb, turn)
    items = list(plan.items)
    out: dict[int, str] = {}
    for n, r in enumerate(rows):
        if not r.get("text") or not r.get("fits"):
            continue
        sel = Selection(round(float(r["start"]), 2), round(float(r["end"]), 2))
        same = next((k for k, i in enumerate(items) if i.kind == "planned" and i.old_text == "" and i.status == "planned"
                     and abs(i.selection.start - sel.start) < 0.05), None)
        if same is not None:
            items[same] = replace(items[same], new_text=r["text"], selection=sel)
            out[n] = items[same].item_id
            continue
        item = PlanItem(item_id=f"i{len(items) + 1}", selection=sel, old_text="", new_text=r["text"], speaker=None,
                        mix="layer", delivery=None, reason="", kind="planned", enabled=True, status="planned")
        items.append(item)
        out[n] = item.item_id
    if out:
        wb.repo.update_plan(turn.project_id, turn.plan_id, items=tuple(items))
    return out


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
        return ToolResult("No voices are available.", step="Looked for voices: none")
    made = {m["voice_id"]: m for m in _made_voices(wb, turn)}
    out = ["Voices that can speak a line (voice_id · name · who · how they sound):"]
    shared = _project_voices(wb, turn)
    for v in shared:
        # Folders: the project's voices first; one that carries consent needs no new consent here.
        out.append(f"- {v['voice_id']} · {v['name']} · in this project" + (f" · {v['description']}" if v.get("description") else "")
                   + (" · consent given" if v.get("consent_granted_at") else ""))
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
        return ToolResult(f"The voice library could not be searched ({exc}).", step="Searched the voice library: unavailable")
    if gender:
        hits = [h for h in hits if (h.get("gender") or "").lower() == gender]
    hits = hits[:8]
    if not hits:
        return ToolResult("Nothing in the library matched. Searching needs an accent "
                          "(indian, british, american, australian, …); the description narrows it in your own judgement.",
                          step="Searched the voice library: nothing found")
    out = ["Library voices, most used first (name · who · how they sound · voice_id · owner_id). Not in the catalogue yet: "
           "add_voice_from_library puts one there (a voice slot, no credits); the description is yours to judge against:"]
    for h in hits:
        who = ", ".join(str(x).replace("_", " ") for x in (h.get("gender"), h.get("accent"), h.get("age")) if x)
        out.append(f"- {h['name']} · {who} · {h.get('description', '')[:120]} · {h['voice_id']} · {h.get('public_owner_id', '')}")
    return ToolResult("\n".join(out), step=f"Searched the voice library: {len(hits)} found")


def _estimate(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    chars, usd = wb.estimate_usd(args["text"])
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    return ToolResult(f"About {chars} voice characters, ${usd:.2f}. This turn has spent ${spent:.2f} of ${turn.budget.usd:.2f}.")


def _project_state(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    spent_turn = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    spent_all = wb.ledger.spent_usd(turn.project_id)
    out = [f"Autonomy: {'Check with me' if turn.autonomy == 'ask' else 'Just do it'}. "
           f"This turn: ${spent_turn:.2f} of ${turn.budget.usd:.2f}; the video: ${spent_all:.2f}."]
    summary = wb.spend(turn.project_id)
    if summary:
        out.append(spend_state(summary))
    items = [i for i in (plan.items if plan else ()) if i.kind == "planned" and i.status != "dismissed"]
    if not items:
        out.append("No lines planned or voiced yet.")
    for i in items:
        out.append(f"- {i.item_id} at {i.selection.start:.1f}–{i.selection.end:.1f} s: “{i.new_text}”: {i.status}"
                   + (f", take {i.candidate_id}" if i.candidate_id else ""))
    state = wb.render_state(turn.project_id) if wb.render_state else {}
    out.extend(shipped_lines(wb.edits(turn.project_id), (state or {}).get("mix")))
    out.append(render_line(state))
    return ToolResult("\n".join(out))


_MIX_WORDS = {"layer": "layered over the picture and sound", "over": "over the picture", "replace": "replacing the words",
              "concatenate": "added after the line, the picture holding", "remove": "the words removed"}


def spend_state(summary: dict) -> str:
    """The money, by scope, as the user sees it: "Spend: this turn $x · video
    $y · project $z"; a standalone video has no project part."""
    turn_usd = (summary.get("turn") or {}).get("spent_usd", 0.0)
    parts = [f"this turn ${turn_usd:.2f}", f"video ${summary['video']['spent_usd']:.2f}"]
    if summary.get("project"):
        parts.append(f"project ${summary['project']['spent_usd']:.2f}")
    return "Spend: " + " · ".join(parts)


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


def shipped_lines(edits: Sequence[Any], mix: dict | None = None) -> list[str]:
    """What is in the video already, one line per live edit, for the agent's
    view of the project (20e). Layered edits stack: two over the same span
    both play. An added line says its role and, from the last render's mix,
    how it sits: a bed how far under the voices, a voice how far over the rest."""
    measured = {ln.get("edit_id"): ln for ln in ((mix or {}).get("lines") or [])}
    live = [e for e in edits if not getattr(e, "reverted", False)]
    if not live:
        return []
    out = ["In the video already (shipped; undo_edit takes one out):"]
    for e in live:
        sel = e.plan.selection
        words = f"“{e.plan.new_text}”" if e.plan.new_text else "(silence)"
        how = _MIX_WORDS.get(e.plan.mix, e.plan.mix)
        if e.plan.mix in ("layer", "over", "concatenate"):
            role = role_of(e.plan)
            offset = getattr(e.plan, "offset_db", None)
            how += f", {role}" + (f" {offset:+.0f} dB" if offset else "")
            m = measured.get(e.edit_id) or {}
            if role == "bed" and m.get("alone"):
                how += " (no speech here, so it plays nearly full)"
            elif role == "bed" and m.get("under_db") is not None:
                how += f" (sits {m['under_db']:.0f} dB under the voices" + (", ducking while they speak)" if m.get("ducks") else ")")
            if m.get("ratio_db") is not None:
                how += f" (heard {m['ratio_db']:.0f} dB over everything else)"
            if m.get("flag"):
                how += f". Not clear: {m['flag']}"
        out.append(f"- {e.edit_id} at {sel.start:.1f}–{sel.end:.1f} s: {words}, {how}")
    return out


# ── free: the project around the video (Folders), and Help ───────────────────

def _list_project_videos(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    project = wb.project(turn.project_id)
    if not project:
        return ToolResult("This video is in no project; it has no sister videos.", step="Looked for sister videos: none")
    sisters = list(project.get("videos") or [])
    if not sisters:
        return ToolResult(f"{project.get('name')} holds no other video yet.", step="Looked for sister videos: none")
    out = [f"The other videos in {project.get('name')} (read only; this turn changes only its own video):"]
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
        return ToolResult("This video is in no project; there are no reference files.", step="Looked for reference files: none")
    files = list(project.get("files") or [])
    if not files:
        return ToolResult(f"{project.get('name')} has no reference files yet.", step="Looked for reference files: none")
    query = (args.get("query") or "").strip()
    unread = [f["name"] for f in files if not (f.get("text") or "").strip()]
    if not query:
        return ToolResult("The reference files: " + ", ".join(f["name"] for f in files) + ". Say what to look for."
                          + (f" No text could be read from {', '.join(unread)}." if unread else ""), step="Listed the reference files")
    found = passages_of(files, query)
    if not found:
        return ToolResult(f"Nothing in the reference files mentions “{query}”. The files: " + ", ".join(f["name"] for f in files) + "."
                          + (f" No text could be read from {', '.join(unread)}." if unread else ""),
                          step=f"Searched the reference files for “{query[:40]}”: nothing found")
    out = [f"Passages about “{query}” (file · passage):"]
    out.extend(f"- {name} · {piece}" for name, piece in found)
    return ToolResult("\n".join(out), step=f"Searched the reference files for “{query[:40]}”: {len(found)} found")


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
        return ToolResult(f"Help could not be searched ({exc}).", step="Looked in Help: unavailable")
    if not hits:
        return ToolResult(f"Help has no article about “{query}”. Say so rather than guess at a feature.",
                          step=f"Looked in Help for “{query[:40]}”: nothing found")
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
    return f" {used} of {limit} voice slots are used" + (", nearly full. Delete a voice before making more." if limit - used <= 5 else ".")


def _plan(wb: Workbench, turn: Turn) -> Plan:
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    if plan is None:
        raise RuntimeError("the turn's plan is gone")
    return plan


def _word_check(wb: Workbench, turn: Turn, text: str, candidate: Any):
    """A3: the take's words (its transcript) against the project's word rules.
    Nothing to check for a standalone video or one whose project has none."""
    from app.agent.word_rules import WordCheck, check_take
    view = wb.project(turn.project_id) if wb.project is not None else None
    found = (view or {}).get("rules") or []
    if not found:
        return WordCheck()
    heard = [w.text for w in (getattr(candidate, "words", None) or ())]
    return check_take(text, heard, found, typed=turn.said)


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
    if existing is None and line_no and not item_id:
        # One line, one item (20d, p60): a retry that names only the line re-voices
        # the item already on that line instead of starting a second one.
        hit = next((ln for ln in lines if ln.index == int(line_no)), None) if str(line_no).isdigit() else None
        if hit is not None:
            existing = next((i for i in reversed(plan.items) if i.kind == "planned" and i.old_text
                             and i.status not in ("dismissed", "approved")
                             and abs(i.selection.start - hit.start) < 0.01 and abs(i.selection.end - hit.end) < 0.01), None)

    if existing is None and not item_id and not line_no and args.get("start") is not None:
        # A line planned with its words (plan_lines) is voiced as its own item, even when the call names only its start.
        at = float(args["start"])
        existing = next((i for i in plan.items if i.kind == "planned" and i.old_text == "" and i.status == "planned"
                         and abs(i.selection.start - at) < 0.05), None)

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

    from app.agent import fitting
    from app.media import fit as fitmod
    fit = {"natural": "start", "stretch": "stretch"}.get(args.get("fit") or "fit")
    picture = args.get("picture") or "default"
    flex_max = 1.0 if picture == "as shot" or (picture == "default" and old_text == "") else None
    settings = voice_settings_of(args)
    speed = float((settings or {}).get("speed") or 1.0)
    window = round(selection.end - selection.start, 3)
    # Pre-flight (p61): the line's length at the voice's own measured rate,
    # before anything is paid. Too long for its window: refused, free.
    estimate = None
    if fit is None and mix != "concatenate":
        rate, takes = fitting.voice_rate(wb.repo, _rate_voice(wb, turn, voice_id, own, speaker))
        if old_text and not takes and window > 0:
            # A replacement in a voice not measured yet: the pace the line was spoken at.
            rate = min(7.0, max(2.5, fitmod.syllables(old_text) / window))
        estimate = fitmod.estimate_seconds(text, rate, speed)
        check = fitting.preflight(text, window, rate, speed, 1.0 if flex_max == 1.0 else fitmod.DEFAULT_MAX_FLEX)
        if check:
            return ToolResult(fitting.refusal_text(check),
                              step=f"Checked “{_short(text)}” before voicing: about {check['estimate']:.1f} s for {window:.1f} s, too long")
    retry = existing is not None and existing.item_id in turn.fit_failed

    chars, usd = wb.estimate_usd(text)
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    refusal = turn.budget.refuses(spent, usd)
    if refusal:
        if retry or turn.fit_failed:
            # The lines that ran long are asked about together, once, at the end of the turn.
            turn.budget.refused_usd = 0.0
            return ToolResult("The turn's cap does not cover voicing this now. Do not ask about it on its own: finish "
                              "what you can, then close the turn; the editor asks the user once about every line that "
                              "needs a shorter version.")
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

    direction = (args.get("direction") or "").strip() or None
    delivery = delivery_of(direction)
    model = model_for(text, args.get("model"))
    role = args.get("role") if args.get("role") in ROLES else None
    offset_db = float(args.get("offset_db") or 0.0) or None
    if existing is None:
        item = PlanItem(item_id=f"i{len(plan.items) + 1}", selection=selection, old_text=old_text, new_text=text,
                        speaker=speaker, mix=mix, delivery=delivery, reason=direction or "", kind="planned",
                        enabled=True, status="planned")
        wb.repo.update_plan(turn.project_id, turn.plan_id, items=plan.items + (item,))
    else:
        item = existing
    begin = getattr(wb.repo, "begin_attempt", None)
    attempt = begin(turn.project_id, turn.plan_id, item.item_id, new_text=text, delivery=delivery, reason=direction or "",
                    error=None, selection=selection, mix=mix) if begin else 0
    if not begin:
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="working", new_text=text,
                            delivery=delivery, reason=direction or "", error=None, selection=selection, mix=mix)

    # The line's Job (one processing model): the one the user's Go queued for this item, or a new one.
    jobs = wb.jobs or NO_JOBS
    job_id = jobs.claim(turn.project_id, item.item_id, text=text, voice_name=name, params={
        "plan_id": turn.plan_id, "selection": [selection.start, selection.end], "text": text, "voice_id": voice_id,
        "fit": fit, "mix": mix, "delivery": delivery, "voice_notes": list(voice_notes), "voice_settings": settings,
        "model": model, "flex_max": flex_max, "role": role, "offset_db": offset_db})

    def step(progress: float, what: str) -> None:
        turn.report(turn.progress, what)
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, progress=what)
        jobs.step(job_id, what)

    def voice_and_report() -> ToolResult:
        if retry:
            turn.fit_retried.add(item.item_id)
        beat_at, key_word = args.get("beat_at"), (args.get("key_word") or "").strip()
        beat = {"at": float(beat_at), "key_word": key_word} if isinstance(beat_at, (int, float)) and beat_at >= 0 else None

        def voice_it(sel: Selection, sets: dict | None, *, held: bool = False, flex: float | None = flex_max) -> Any:
            """One call to the pipeline; `held` only reuses the take already paid for (None when there is none)."""
            fn = wb.held_take if held else wb.generate
            if fn is None:
                return None
            return fn(turn.project_id, record, wb.repo.next_candidate_id(turn.project_id), sel, text, voice_id,
                      fit, mix, step, delivery=delivery, voice_notes=voice_notes,
                      voice_settings=sets, model=model, flex_max=flex, max_regenerations=0,
                      role=role, offset_db=offset_db)

        def measure(outcome: str, sets: dict | None, win: float) -> dict:
            """The take's own length against the estimate: the voice's rate learns from it, and the log keeps both."""
            got = wb.measured() or {}
            if got.get("seconds"):
                fitting.learn(wb.repo, voice_id, text, float(got["seconds"]), float(got.get("speed") or (sets or {}).get("speed") or 1.0),
                              estimate=estimate if sets == settings else None, window=win, video=turn.project_id,
                              item=item.item_id, outcome=outcome, at=wb.now())
            return got

        def climb(first: Exception, seen: dict) -> tuple[Any, Selection, list[str], Exception]:
            """The fit ladder (p61), in order, after the take's own pauses are trimmed:
            start up to 150 ms early; the model's own speed up to 1.15 on a retake;
            let the next added line flow later if it has room before its beat; the
            picture eases only where allowed. (candidate or None, its span, what was tried, the last mismatch.)"""
            from app.media.ffmpeg import MAX_TEMPO
            tried = ["trimmed the take's pauses, lead-in and tail, and sped the speech up to 1.25×"]
            last, sel, sets = first, selection, settings
            if old_text == "" and mix == "layer":
                early = round(max(0.0, _end_before(wb, turn, item.item_id, sel.start), sel.start - fitmod.EARLY_START), 2)
                ahead = round(sel.start - early, 2)
                if ahead >= 0.01:
                    moved_to = Selection(early, sel.end)
                    try:
                        got = voice_it(moved_to, sets, held=True)
                    except Exception as exc:  # noqa: BLE001
                        if not _too_long(exc):
                            return None, sel, tried, last
                        got, last = None, exc
                        tried.append(f"started {ahead * 1000:.0f} ms early")
                        sel = moved_to
                    if got is not None:
                        return got, moved_to, tried + [f"started {ahead * 1000:.0f} ms early"], last
                else:
                    tried.append("could not start earlier: the line before ends there")
            current = float((sets or {}).get("speed") or 1.0)
            want = current * last.natural / max(0.1, (sel.end - sel.start) * MAX_TEMPO)
            if seen.get("faster_tried"):
                tried.append(f"a retake at {float(seen['faster_tried']):.2f}× speed")
            elif current >= fitmod.MODEL_SPEED_MAX - 1e-6:
                tried.append(f"already spoken at {current:.2f}× by the model")
            elif want > fitmod.MODEL_SPEED_MAX:
                tried.append(f"a faster retake would need {want:.2f}× speed, past the {fitmod.MODEL_SPEED_MAX:.2f}× that still sounds natural")
            elif _over_cap(wb, turn, text):
                tried.append("a faster retake would pass this turn's cap")
            else:
                faster = {**(sets or {}), "speed": round(min(fitmod.MODEL_SPEED_MAX, max(math.ceil(want * 100) / 100, current + 0.05)), 2)}
                jobs.step(job_id, f"Retake at {faster['speed']:.2f}x")
                try:
                    got = voice_it(sel, faster)
                    measure("fit", faster, sel.end - sel.start)
                    return got, sel, tried + [f"a retake at {faster['speed']:.2f}× speed"], last
                except Exception as exc:  # noqa: BLE001
                    if not _too_long(exc):
                        return None, sel, tried, last
                    measure("too long", faster, sel.end - sel.start)
                    last, sets = exc, faster
                    tried.append(f"a retake at {faster['speed']:.2f}× speed")
            extra = round(last.natural / MAX_TEMPO - (sel.end - sel.start) + 0.02, 2)
            if extra > 0 and old_text == "" and mix == "layer":
                room, nxt, shift = _flow_room(wb, turn, item.item_id, sel, extra)
                if room >= extra:
                    longer = Selection(sel.start, round(min(duration, sel.end + extra), 2))
                    try:
                        got = voice_it(longer, sets, held=True)
                    except Exception as exc:  # noqa: BLE001
                        if not _too_long(exc):
                            return None, sel, tried, last
                        got, last = None, exc
                        tried.append(f"ran on {extra:.1f} s into the room after it, still too long")
                    if got is not None:
                        flowed = _flow_later(wb, turn, nxt, shift) if nxt is not None and shift > 0 else ""
                        return got, longer, tried + [f"ran on {extra:.1f} s into the room after it" + flowed], last
                else:
                    tried.append("the next line had no room before its beat" if nxt is not None else "no free room after it")
            if flex_max is None or flex_max > 1.0:
                tried.append("let the picture ease, as allowed")
            else:
                tried.append("the picture may not ease unless you allow it")
            return None, sel, tried, last

        before = wb.ledger.spent_usd(turn.project_id)
        used, tried = selection, []
        try:
            # One take per call (the adapter's takes-by-duration aside): a take that
            # fails the sound check comes back with its report, and the retry — with
            # a different direction, voice or wording — is Voltage's own call.
            candidate = voice_it(selection, settings)
            measure("fit", settings, window)
        except Exception as exc:  # noqa: BLE001 — the model hears why and decides; nothing crashes the turn
            candidate = None
            if _too_long(exc):
                seen = measure("too long", settings, window)
                candidate, used, tried, last = climb(exc, seen)
                if candidate is None:
                    return _ran_long(wb, turn, item, attempt, text, window, last, tried, before, voice_it, used, settings, flex_max,
                                     retried=item.item_id in turn.fit_retried, beat=beat)
            if candidate is None:
                reason = str(exc) or type(exc).__name__
                finish = getattr(wb.repo, "finish_attempt", None)
                state = finish(turn.project_id, turn.plan_id, item.item_id, attempt, error=reason) if finish else "failed"
                if not finish:
                    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="failed", error=reason, progress=None)
                kept = (f" {item.item_id} keeps its earlier take {wb.repo.get_plan(turn.project_id, turn.plan_id).item(item.item_id).candidate_id}, ready to hear."
                        if state == "ready" else f" {item.item_id} has no take.")
                return ToolResult(f"The take could not be made: {reason}{kept}", step=f"Could not voice “{text[:40]}”: {reason[:80]}")
        cost = max(0.0, wb.ledger.spent_usd(turn.project_id) - before)
        # A3: after the sound and fit checks, the take's own words against the project's words.
        words_check = _word_check(wb, turn, text, candidate)
        finish = getattr(wb.repo, "finish_attempt", None)
        if finish:
            extra_changes = {"selection": used} if used != selection else {}
            state = finish(turn.project_id, turn.plan_id, item.item_id, attempt, candidate_id=candidate.candidate_id, fit=candidate.plan.fit, note=None,
                           fit_failure=None, beat=beat, word_rule=words_check.to_dict(), **extra_changes)
            if state == "stale":
                return ToolResult(f"Take {candidate.candidate_id} was made, but a newer attempt on {item.item_id} has started; "
                                  "it is kept in the item's history, not shown.")
        else:
            wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="ready", candidate_id=candidate.candidate_id,
                                progress=None, error=None, fit=candidate.plan.fit, word_rule=words_check.to_dict())
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
        beat_at, key_word = args.get("beat_at"), (args.get("key_word") or "").strip()
        landing, landed = "", None
        if key_word and isinstance(beat_at, (int, float)) and beat_at >= 0:
            from app.agent.landing import landing_note
            landing, miss = landing_note(candidate.words, took.start, key_word, float(beat_at))
            landed = {"beat_at": float(beat_at), "key_word": key_word, "miss": miss}
            if miss is not None:
                wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, beat={**(beat or {}), "miss": miss},
                                    note=None if abs(miss) <= 0.3 else f"“{key_word}” lands {abs(miss):.1f} s {'late' if miss > 0 else 'early'} for its beat.")
        if len(tried) > 1:
            notes += f" It ran long at first; it fits now after: {'; '.join(tried)}."
        if words_check.breaks:
            notes += (f" {words_check.sentence()} It is marked on the line and is not yours to add or to offer as your pick: "
                      "voice it again (same item_id) so the term comes out as the project says it, or change the wording.")
        elif words_check.warnings:
            notes += " " + words_check.sentence()
        text_out = (f"Take {candidate.candidate_id} on {item.item_id}, {whose}, {where}. It {verdict}.{notes}{wps}{landing}{how_said} "
                    f"Cost ${cost:.2f}.{' The item moved to the new span.' if moved else ''} "
                    f"The user can hear it now; voice it again (same item_id) to try another direction or wording, "
                    f"or with a new start and end to move it.")
        how = f" · {direction}" if direction else ""
        return ToolResult(text_out, step=f"Voiced “{text[:48]}{'…' if len(text) > 48 else ''}” with {name}{how}", cost_usd=cost,
                          data={"landing": landed} if landed else None)


    made_before = len(turn.takes)
    try:
        result = voice_and_report()
    except BaseException as exc:
        jobs.settle(job_id, ok=False, code="unknown", text=str(exc) or type(exc).__name__)
        raise
    _settle_line_job(wb, turn, jobs, job_id, item.item_id, result, made=len(turn.takes) > made_before)
    return result


def _settle_line_job(wb: Workbench, turn: Turn, jobs: Any, job_id: str | None, item_id: str, result: ToolResult,
                     *, made: bool) -> None:
    """The line's Job ends the way the attempt did: done with its take, or
    failed with the reason the row shows (too long for its gap, the vendor)."""
    if job_id is None:
        return
    if made:
        jobs.settle(job_id, ok=True, cost=result.cost_usd)
        return
    if "a newer attempt on" in result.text:
        jobs.settle(job_id, ok=False, code="cancelled", text="A newer try on this line replaced it.")
        return
    after = _plan(wb, turn).item(item_id)
    history = getattr(after, "history", ()) if after else ()
    last_error = str((history[-1].get("error") if history else None) or "")
    failure = getattr(after, "fit_failure", None) if after else None
    if failure and last_error.startswith("Too long"):
        text = f"Too long for its gap: needs {failure['needs']:.1f} s, has {failure['has']:.1f} s."
        jobs.settle(job_id, ok=False, code="too_long", text=text, cost=result.cost_usd)
        return
    # The attempt's own reason: the item's error, or (when an earlier take still stands) its last history entry.
    reason = (getattr(after, "error", None) if after else None) or last_error or None
    jobs.settle(job_id, ok=False, code="vendor_failed", text=reason or "The take could not be made.", cost=result.cost_usd)


def _statements(record) -> list:
    from app.domain.transcript import statements_of
    return list(statements_of(record.transcript))


# ── lines that run long (p61) ─────────────────────────────────────────────────

def _short(text: str, n: int = 40) -> str:
    return text[:n] + ("…" if len(text) > n else "")


def _too_long(exc: Exception) -> bool:
    """A take that came back longer than its gap (SpanMismatch, too long)."""
    from app.media.ffmpeg import SpanMismatch
    return isinstance(exc, SpanMismatch) and exc.natural > exc.target


def _rate_voice(wb: Workbench, turn: Turn, voice_id: str, own: bool, speaker: str | None) -> str:
    """The voice whose measured rate a line is estimated at: the one asked
    for; for the speaker's own voice their clone (or the voice picked for them)."""
    if not own:
        return voice_id
    if speaker:
        spk = next((s for s in wb.speakers(turn.project_id) if s.label == speaker), None)
        if spk is not None:
            return getattr(spk, "voice_id", None) or getattr(spk, "clone_voice_id", None) or wb.default_voice()
    return wb.default_voice()


def _over_cap(wb: Workbench, turn: Turn, text: str) -> bool:
    """Whether voicing `text` again would pass this turn's cap (asked without
    marking it refused: the ladder only skips the rung)."""
    _, usd = wb.estimate_usd(text)
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    if turn.budget.excused is not None:
        spent = max(0.0, spent - turn.budget.excused())
    return spent + usd > turn.budget.usd + 1e-9


def _added_spans(wb: Workbench, turn: Turn, skip: str) -> list[tuple[float, float, Any]]:
    """Every added line on the clip, as (start, end, item or None for a shipped one)."""
    plan = _plan(wb, turn)
    out = [(i.selection.start, i.selection.end, i) for i in plan.items
           if i.kind == "planned" and i.old_text == "" and i.item_id != skip and i.status not in ("dismissed", "approved")]
    for e in wb.edits(turn.project_id):
        p = getattr(e, "plan", None)
        if p is not None and getattr(p, "mix", "") in ("layer", "over", "concatenate") and not getattr(e, "reverted", False):
            out.append((p.selection.start, p.selection.end, None))
    return sorted(out, key=lambda s: s[0])


def _end_before(wb: Workbench, turn: Turn, item_id: str, start: float) -> float:
    """Where the added line before `start` ends (0 when there is none)."""
    ends = [end for s, end, _ in _added_spans(wb, turn, item_id) if s < start - 1e-6 and end <= start + 0.01]
    return max(ends, default=0.0)


def _flow_room(wb: Workbench, turn: Turn, item_id: str, sel: Selection, extra: float) -> tuple[float, Any, float]:
    """How far a line may run on past its end (the arrangement rule: the next
    added line flows later if it has room before its beat). Returns (room,
    the next line's item or None, how far that line must move)."""
    duration = turn.record.source.duration
    later = [s for s in _added_spans(wb, turn, item_id) if s[0] >= sel.end - 0.01]
    if not later:
        return max(0.0, duration - sel.end), None, 0.0
    start, end, nxt = later[0]
    free = max(0.0, start - _line_gap() - sel.end)
    if nxt is None:                 # a shipped line does not move
        return free, None, 0.0
    after = later[1][0] - _line_gap() if len(later) > 1 else duration
    beat = nxt.beat or {}
    if nxt.candidate_id:
        room = max(0.0, after - end)
        if beat.get("miss") is not None:
            from app.agent.landing import WITHIN
            room = min(room, max(0.0, WITHIN - float(beat["miss"])))
    else:
        from app.agent import fitting
        rate, _ = fitting.voice_rate(wb.repo, wb.default_voice())
        from app.media import fit as fitmod
        room = max(0.0, (end - start) - fitmod.estimate_seconds(nxt.new_text, rate))
        if beat.get("at") is not None:
            room = min(room, max(0.0, float(beat["at"]) - start))
    shift = round(max(0.0, extra - free), 2)
    return free + room, nxt, shift


def _line_gap() -> float:
    from app.media import fit as fitmod
    return fitmod.LINE_GAP


def _flow_later(wb: Workbench, turn: Turn, nxt: Any, shift: float) -> str:
    """Move the next added line later by `shift` seconds: its take as it is
    (nothing voiced again), or its planned span when it has none yet."""
    if nxt.candidate_id and wb.move_take is not None:
        candidate = wb.repo.get_candidate(turn.project_id, nxt.candidate_id)
        if candidate is None:
            return ""
        moved = wb.move_take(turn.project_id, turn.record, candidate, round(candidate.plan.selection.start + shift, 2), None)
        sel = moved.plan.selection
        wb.repo.update_item(turn.project_id, turn.plan_id, nxt.item_id, candidate_id=moved.candidate_id, selection=Selection(sel.start, sel.end))
    else:
        wb.repo.update_item(turn.project_id, turn.plan_id, nxt.item_id,
                            selection=Selection(round(nxt.selection.start + shift, 2), nxt.selection.end))
    return f"; the next line flows {shift:.1f} s later"


def _ran_long(wb: Workbench, turn: Turn, item: PlanItem, attempt: int, text: str, window: float, last: Exception,
              tried: list[str], before: float, voice_it: Callable[..., Any], used: Selection, settings: dict | None,
              flex_max: float | None, *, retried: bool, beat: dict | None) -> ToolResult:
    """Every rung tried and the take still runs long: the item fails with
    exactly what was tried. The paid take is not thrown away: when the picture
    may not ease on its own, the same audio is fitted with the picture eased
    and kept for the user to choose, at no new cost."""
    from app.agent import fitting
    from app.media import fit as fitmod
    needs, has = float(last.natural), window
    eased_id, ease_s = None, None
    if flex_max == 1.0:
        try:
            eased = voice_it(used, settings, held=True, flex=fitmod.USER_EASE_MAX)
        except Exception:  # noqa: BLE001 — too long even with the picture eased: nothing to offer
            eased = None
        if eased is not None:
            factor = getattr(eased.plan, "flex", None) or fitmod.flex_of(eased.fit_notes)
            slot = eased.plan.selection.end - eased.plan.selection.start
            eased_id, ease_s = eased.candidate_id, round(slot * (float(factor) - 1.0), 2) if factor else None
    cost = max(0.0, wb.ledger.spent_usd(turn.project_id) - before)
    n = fitmod.syllables(fitmod.spoken(text))
    budget = fitting.shorter_budget(n, needs, has)
    reason = f"Too long for its gap: needs {needs:.1f} s, has {has:.1f} s."
    finish = getattr(wb.repo, "finish_attempt", None)
    state = finish(turn.project_id, turn.plan_id, item.item_id, attempt, error=reason) if finish else "failed"
    if not finish:
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="failed", error=reason, progress=None)
    failure = {"reason": fitting.TOO_LONG, "needs": round(needs, 2), "has": round(has, 2), "tried": list(tried),
               "syllables": n, "budget": budget, "cost_usd": round(cost, 4), "text": text,
               "eased_candidate_id": eased_id, "ease_s": ease_s if ease_s and ease_s > 0 else None}
    if state == "failed":
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, fit_failure=failure, beat=beat)
        turn.fit_failed[item.item_id] = {"item_id": item.item_id, "text": text, "budget": budget, "has": has, "cost_usd": cost}
    out = [f"The take on {item.item_id} could not be fitted. {reason} "
           f"Tried, in order: {'; '.join(tried)}."]
    if eased_id and failure["ease_s"]:
        out.append(f"The take is kept: with the picture easing {failure['ease_s']:.1f} s it fits, and the user can use it from "
                   "the line at no new cost.")
    if state == "ready":
        out.append(f"{item.item_id} keeps its earlier take.")
    elif retried:
        out.append("It was already tried shorter once this turn; leave it for the user, who can shorten it, let the picture ease "
                   "or discard it from its line.")
    else:
        out.append(f"Rewrite it to about {budget} syllables (it has {n}) and voice it again now on {item.item_id}, once. "
                   "If the turn's cap stops that, finish the rest and close the turn: the editor asks the user once about every "
                   "line that needs a shorter version.")
    out.append(f"Cost ${cost:.2f}.")
    return ToolResult(" ".join(out), step=f"Too long for its gap: “{_short(text)}”, {needs:.1f} s for {has:.1f} s",
                      cost_usd=cost)


def fit_followup(wb: Workbench, turn: Turn) -> str | WaitingForUser | None:
    """At the end of a turn: lines that ran long and were not tried shorter.
    Voltage is told once to try them (when the turn can pay for it), else the
    user is asked once about all of them together. None when there are none."""
    from app.agent import fitting
    if not fitting.pending(turn.fit_failed, turn.fit_retried):
        return None
    plan = wb.repo.get_plan(turn.project_id, turn.plan_id)
    left =[info for info in fitting.pending(turn.fit_failed, turn.fit_retried)
            if plan is None or ((it := plan.item(info["item_id"])) is not None and it.status == "failed")]
    if not left:
        return None
    usd = sum(wb.estimate_usd(i["text"])[1] for i in left)
    spent = wb.ledger.spent_usd_since(turn.project_id, turn.started_at)
    if turn.budget.excused is not None:
        spent = max(0.0, spent - turn.budget.excused())
    affordable = spent + usd <= turn.budget.usd + 1e-9 and turn.budget.calls_made + len(left) <= turn.budget.calls
    if affordable and not turn.fit_nudged:
        turn.fit_nudged = True
        return fitting.nudge(left)
    question, options, details, total = fitting.group_question([{**i, "cost_usd": wb.estimate_usd(i["text"])[1]} for i in left])
    return WaitingForUser(question, options, options[0], gate=True, cost_usd=total, details=details)


def _keep_take(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    plan = _plan(wb, turn)
    item = plan.item(args["item_id"])
    if item is None:
        return ToolResult(f"There is no item {args['item_id']}.")
    candidate = wb.repo.get_candidate(turn.project_id, args["candidate_id"])
    if candidate is None:
        return ToolResult(f"There is no take {args['candidate_id']}.")
    wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, status="ready", candidate_id=candidate.candidate_id,
                        new_text=candidate.plan.new_text, error=None, fit_failure=None)
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
        raise WaitingForUser(f"Design a voice from “{description}”: three previews to hear, about ${usd:.2f}?", cost_usd=usd)
    wb.ensure_spend(turn.project_id)
    turn.report(turn.progress, "Designing a voice")
    jobs = wb.jobs or NO_JOBS
    job_id = jobs.begin(turn.project_id, "design_voice", "Designing a voice", detail={"text": description[:120], "chars": chars})
    before = wb.ledger.spent_usd(turn.project_id)
    try:
        previews = list(wb.design(turn.project_id, description, sample))
    except Exception as exc:  # noqa: BLE001 — the model hears why
        reason = str(exc) or type(exc).__name__
        jobs.settle(job_id, ok=False, code="vendor_failed", text=f"The voice could not be designed: {reason}")
        return ToolResult(f"The voice could not be designed: {reason}", step=f"Could not design a voice: {reason[:80]}")
    cost = max(0.0, wb.ledger.spent_usd(turn.project_id) - before)
    if not previews:
        jobs.settle(job_id, ok=False, code="vendor_failed", text="The voice service sent no previews back.", cost=cost)
        return ToolResult("The vendor sent no previews back.", step="Designed a voice: nothing came back", cost_usd=cost)
    jobs.settle(job_id, ok=True, cost=cost, label=f"{len(previews)} previews to hear")
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
    return ToolResult(text_out, step=f"Designed a voice from “{description[:56]}{'…' if len(description) > 56 else ''}”: {len(rows)} previews to hear",
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
        return ToolResult(f"The voice could not be saved: {reason}", step=f"Could not keep the voice: {reason[:80]}")
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
        return ToolResult(f"The voice could not be added: {reason}", step=f"Could not add {name}: {reason[:80]}")
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
    if out.get("error"):
        return ToolResult(f"Line {line.index} stays where it was: {out['error']}")
    sel = out["selection"]
    return ToolResult(f"Line {line.index} is pinned to play from {sel['start']:.2f} s; the room's sound is where it was, "
                      "and the other lines follow one another around it. It is part of the video already; "
                      "the user can unpin it or undo the move in the transcript.",
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


ROLE_WORD = {"voice": "a Voice", "bed": "a Bed", "effect": "an Effect"}


def _set_role(wb: Workbench, turn: Turn, args: dict) -> ToolResult:
    """2026-10-20: what a line is in the mix, which sets its level against the
    clip's speech: Voice, Bed (under the words, ducking) or Effect; offset_db
    fine-tunes it. Nothing is voiced again. The only speech in its span does
    not become a Bed unless the user said so."""
    role = args.get("role") if args.get("role") in ROLES else "voice"
    offset = float(args.get("offset_db") or 0.0)
    anyway = bool(args.get("user_said_bed"))
    what = ROLE_WORD[role] + (f" ({offset:+.0f} dB)" if offset else "")
    item_id, edit_id = (args.get("item_id") or "").strip(), (args.get("edit_id") or "").strip()

    def only_speech(plan, skip) -> bool:
        return role == "bed" and role_of(plan) != "bed" and not anyway and wb.only_voice is not None \
            and wb.only_voice(turn.project_id, plan, skip)
    refuse = ("It is the only speech in its span: as a Bed it would just be quieter. Ask the user: keep it as Voice, "
              "or play it quietly under (Voice, offset_db -8). Make it a Bed only if they say so (user_said_bed).")
    if item_id:
        if wb.rerole_take is None:
            return ToolResult("Roles cannot be set in this setup.")
        plan = _plan(wb, turn)
        item = plan.item(item_id)
        if item is None or not item.candidate_id:
            return ToolResult(f"There is no voiced item {item_id}.")
        if item.status == "approved":
            return ToolResult(f"{item_id} is in the video; name its edit (edit_id) instead; project_state lists them.")
        candidate = wb.repo.get_candidate(turn.project_id, item.candidate_id)
        if candidate is None:
            return ToolResult(f"The take {item.candidate_id} is gone.")
        if candidate.plan.mix in ("replace", "remove"):
            return ToolResult(f"{item_id} replaces a line of the original speech, which is always a Voice.")
        if only_speech(candidate.plan, (candidate.candidate_id,)):
            return ToolResult(refuse)
        out = wb.rerole_take(turn.project_id, candidate, role, offset)
        wb.repo.update_item(turn.project_id, turn.plan_id, item.item_id, candidate_id=out.candidate_id)
        return ToolResult(f"{item_id} is {what} now, as take {out.candidate_id}; the same audio, not voiced again.",
                          step=f"Made {item_id} {what}")
    if edit_id:
        if wb.rerole_edit is None:
            return ToolResult("Roles cannot be set in this setup.")
        edit = next((e for e in (wb.edits(turn.project_id) if wb.edits else ())
                     if e.edit_id == edit_id and not getattr(e, "reverted", False)), None)
        if edit is not None and only_speech(edit.plan, (edit.edit_id, getattr(edit, "candidate_id", ""))):
            return ToolResult(refuse)
        if turn.autonomy == "ask" and not turn.commit_approved:
            raise WaitingForUser(f"Make {edit_id} {what}?", ("Yes", "Not yet"), "Yes")
        out = wb.rerole_edit(turn.project_id, edit_id, role, offset)
        if out is None:
            return ToolResult(f"There is no added line {edit_id} in the video (a line of the original speech is always a Voice); project_state lists them.")
        return ToolResult(f"{edit_id} is {what} now as edit {out['edit_id']}; the video is rendered again when something ships next.",
                          step=f"Made {edit_id} {what}")
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
    out = [f"Take {c.candidate_id}: {'passed' if r.passed else 'did not pass'} the sound check" + (f" ({'; '.join(scores)})" if scores else "") + "."]
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
    if turn.batch:
        # F4: in a batch the user adds lines from the batch board ("Add all that passed"), never the turn.
        return ToolResult(f"This video is part of a batch: its {n} ready {'line waits' if n == 1 else 'lines wait'} for the user "
                          "to add from the batch board. Do not ship; say what is ready and end the turn.")
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
    # Each option is {label, detail} (a short label for the button, the full
    # sentence beneath it; "" for none), or a plain string.
    pairs: list[tuple[str, str | None]] = []
    for o in args.get("options") or []:
        label, detail = (o.get("label"), o.get("detail")) if isinstance(o, dict) else (o, None)
        label, detail = (label or "").strip(), (detail or "").strip()
        if label:
            pairs.append((label, detail if detail and detail != label else None))
    pairs = pairs[:3]
    if len(pairs) < 2:
        return ToolResult("Give two or three options to choose from.")
    options = tuple(label for label, _ in pairs)
    raise WaitingForUser(args["question"].strip(), options, (args.get("guess") or "").strip() or None, gate=False,
                         details=tuple(detail for _, detail in pairs))


# ── the registry ──────────────────────────────────────────────────────────────

TOOLS: tuple[Tool, ...] = (
    Tool("look_at_frames", "Look at the picture: up to six frames of the clip as images, evenly spaced, or the ones nearest the times you name.",
         _schema({"at": {"type": "array", "items": {"type": "number"}, "description": "Times in seconds to look at; empty for an even spread."}}), Guard.FREE, _look_at_frames),
    Tool("read_transcript", "Read every spoken line with who says it, when, and how many syllables its slot can hold. Says so when no one speaks.",
         _schema({}), Guard.FREE, _read_transcript),
    Tool("find_room", "Where a new line can go: the whole clip when there is no speech (with its placement windows, beat to beat), "
         "else the pause after each line. Every window comes with its length and the syllables it holds at the voice's measured rate.",
         _schema({"voice_id": {"type": "string", "description": "The voice that will speak, for its measured rate; empty for the default."}}),
         Guard.FREE, _room),
    Tool("plan_lines", "Before voicing several added lines, plan them together: each line's window (ending where the next line starts, "
         "less a breath), the syllables it holds at the voice's measured rate, whether the words fit, and how much of the clip is talk "
         "(commentary: under about 70%). Free. Write each line to its budget, then voice them.",
         _schema({"voice_id": {"type": "string", "description": "The voice that will speak; empty for the default."},
                  "speed": {"type": "number", "description": "The model speed the lines will be voiced at; 1 for natural."},
                  "commentary": {"type": "boolean", "description": "True for commentary or narration over the picture (the 70% rule)."},
                  "lines": {"type": "array", "description": "The lines in any order.", "items": _schema({
                      "start": {"type": "number", "description": "Seconds."},
                      "end": {"type": "number", "description": "Seconds; -1 to end where the next line starts."},
                      "text": {"type": "string", "description": "The words (audio tags allowed); empty to get just the budget."}})}}),
         Guard.FREE, _plan_lines),
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
         "`settings` as the vendor's dials, and for v3/v4 audio tags inside `text`, such as [sighs], [laughs], [whispers], [exhales], "
         "[long pause], [excited], [sad], [curious]; an ellipsis for a held beat, CAPITALS for weight. "
         "Models: v4 (the vendor's newest; the most emotive, performs tags, keeps the sentence around a seam), v3 (expressive, performs tags, "
         "but a replacement inside someone's sentence loses that context), v2 (the steadiest, finest style control, reads a tag as words so tags are stripped). "
         "Null picks the default, v4 when the text carries tags. Before paying, the line's length is estimated at the voice's "
         "measured rate: one too long for its window is refused, free, with the syllables to rewrite to. A take that still runs long "
         "climbs the fit ladder (an earlier start, a faster retake, the next line flowing later) before it fails.",
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
                  "role": {"type": "string", "enum": ["voice", "bed", "effect"], "description": "What the line is in the mix. voice = words meant to be understood (at the clip's speech level). bed = music, a crowd, cheers, ambience: under the words and ducking while they play. effect = a sound at the speech level."},
                  "offset_db": {"type": "number", "description": "A fine-tune on top of the role's level, -24 to +6 dB; 0 for none. Speech wanted 'in the background' is a voice with a negative offset."},
                  "item_id": {"type": "string", "description": "An existing item to voice again; empty for a new one."},
                  "beat_at": {"type": "number", "description": "The time of the beat this line is written for (seconds); -1 for none. With key_word, the take reports where the word lands."},
                  "key_word": {"type": "string", "description": "The word that should land on the beat; empty for none."}}), Guard.SPEND, _synthesize_take, strict=True),
    Tool("keep_take", "Put an earlier take back on an item (after voicing it again and preferring the first).",
         _schema({"item_id": {"type": "string"}, "candidate_id": {"type": "string"}}), Guard.FREE, _keep_take),
    Tool("drop_item", "Drop a planned or voiced line from the plan (not one that has shipped).",
         _schema({"item_id": {"type": "string"}}), Guard.FREE, _drop_item),
    Tool("design_voice",
         "Make a voice from words when the catalogue has nothing that fits: three previews the user can hear (about 25 s each, the same sample text), "
         "for the price of the sample text (the vendor's own is about 350 characters). Keep one with save_voice. Costs money.",
         _schema({"description": {"type": "string", "description": "Who is speaking: age, gender, accent, texture, manner. For example: an Indian woman near fifty, unhurried, a smile in the voice, slight rasp."},
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
    Tool("shift_line", "Move a spoken line to another time, as it was spoken: nothing is voiced. The line is pinned there and the other lines follow one another around it; a replacement moves with its line. Part of the video at once.",
         _schema({"line": {"type": "integer"}, "to": {"type": "number", "description": "Where the words should start, in seconds."}}), Guard.COMMIT, _shift_line, strict=True),
    Tool("move_item", "Place a voiced item's take at another time, the same audio, nothing voiced again.",
         _schema({"item_id": {"type": "string"}, "start": {"type": "number", "description": "Seconds."}}), Guard.FREE, _move_item),
    Tool("set_role", "What a line is in the mix, without voicing it again: voice (words, at the clip's speech level), bed (music, crowd, cheers, ambience: under the voices, ducking while they speak) or effect; offset_db fine-tunes it. A proposal by item_id, or an added line in the video by edit_id. Lines of the original speech are always voices.",
         _schema({"item_id": {"type": "string", "description": "A proposal; empty when naming an edit."},
                  "edit_id": {"type": "string", "description": "An added line in the video; empty when naming an item."},
                  "role": {"type": "string", "enum": ["voice", "bed", "effect"]},
                  "offset_db": {"type": "number", "description": "-24 to +6 dB on top of the role's level; 0 for none."},
                  "user_said_bed": {"type": "boolean", "description": "True only when the user asked for the only speech in its span to be a Bed."}}), Guard.COMMIT, _set_role),
    Tool("measure", "The full sound check of a take: its scores, what was done to fit it, how it was spoken.",
         _schema({"candidate_id": {"type": "string"}}), Guard.FREE, _measure),
    Tool("ship", "Make the voiced lines part of the video and render it. Only when the user asks for it, or said just do it and the work is done.",
         _schema({"item_ids": {"type": "array", "items": {"type": "string"}, "description": "Which items; empty for every voiced line."},
                  "anyway": {"type": "boolean", "description": "Ship a take that did not pass its check. Only when the user said to ship it as it is."}}),

         Guard.COMMIT, _ship, strict=True),
    Tool("undo_edit", "Take a shipped edit back out of the video (project_state lists them). A redo of a line that is in the video already: voice the new take, ship it, then undo the old edit, so lines do not pile up.",
         _schema({"edit_id": {"type": "string"}}), Guard.COMMIT, _undo_edit),
    Tool("ask", "Stop and ask the user one thing, with two or three options and your own guess. The turn ends; their answer starts the next. "
         "Keep each option's label short (about 40 characters, it is the button); put a longer sentence in its detail.",
         _schema({"question": {"type": "string"},
                  "options": {"type": "array", "items": _schema({
                      "label": {"type": "string", "description": "The button: a few words, about 40 characters at most."},
                      "detail": {"type": "string", "description": "The full sentence shown under the label; empty for none."}})},
                  "guess": {"type": "string", "description": "The label of the option you would take; empty for none."}}), Guard.FREE, _ask, strict=True),

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
