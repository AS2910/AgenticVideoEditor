"""The agent's planning, by Claude (Phase 13).

One structured-output call reads the goal with the whole transcript and
returns the changes that carry it out; a second, smaller call offers a shorter
wording when a line runs long. Effort is low for the shortening (one line) and
medium for the plan (it has to read everything). As with intent reading, the
reply is validated against a schema so the app never parses prose.
"""
from __future__ import annotations

import re
from typing import Literal, Sequence

import anthropic
from pydantic import BaseModel, Field

from app.adapters.claude_intent import IntentConfigError, IntentError, MODEL
from app.orchestrator.intent import Meter
from app.orchestrator.planner import (
    Change, ItemChange, ItemView, Line, Proposal, Question, Reading, Revision, Role,
)

MAX_TOKENS = 4000

SYSTEM = """\
You plan edits for a video dialogue editor. The user has a finished video and \
describes, in their own words, how its spoken message should change. You read \
every line of the transcript and decide which lines to change and what each \
should say instead.

The editor can only re-voice dialogue: say new words in a line's place \
("replace"), or add a new line right after one. An added line normally plays \
over the picture that follows ("over": the video keeps moving); only when the \
goal asks for the picture to wait, or nothing could play over it, use \
"concatenate" (the picture holds while it plays). It cannot change visuals, \
music, or pacing.

Rules:
- `edits` are the changes the goal asks for. Keep each as close to the original \
line as the goal allows; change only what the goal needs. For a replaced line \
write the full new line. Keep each speaker's own way of talking.
- A replaced line has to be spoken in the time its slot allows. Each line \
shows its syllables now and how many fit ("7 syl now, up to 9 fit"): keep a \
replacement within that budget, counting syllables as you write. An added \
line can be any length but should stay under about 12 syllables.
- `suggestions` are changes the goal implies but did not name — a word that \
reads oddly once the goal is applied, a line that now contradicts it. Offer at \
most three, and only when genuinely useful. They are not applied unless the \
user adds them.
- `summary` is one or two plain sentences to the user: what you read and what \
you plan, e.g. "I read all 20 lines. Three changes do it."
- `reason` is one short sentence to the user saying why this change, and why \
here, e.g. "Added right after he confirms the feed — the one calm beat in the \
clip." Never a label.
- `findings` are two to four short observations you made while reading, in \
the order you made them, each a plain sentence: "The brand name is said once, \
at 0:07." "The offer isn't mentioned anywhere yet, so it has to be added."
- `question`: at most one thing you genuinely need to know before the plan is \
right — usually who should carry a new line when the goal doesn't say. Give \
two or three `options`, and your `guess` (one of the options). Still return \
the full plan built on your guess, so the user can simply say go. Leave it \
null when the goal is clear.
- `line` is the line's number from the transcript. `speaker` names who says \
an added line when it is not the person who spoke the line it follows.
- `new_text` is only the spoken words. Never put a name or a label such as \
"Shopkeeper:" in front of them; they would be read aloud.
If the goal cannot be met with dialogue changes, return no edits and say why \
in `summary`.\
"""

SHORTEN_SYSTEM = """\
You shorten one line of video dialogue so it can be spoken in less time. Keep \
its meaning, the speaker's tone and any names or numbers. Reply with the new \
line only.\
"""


READ_SYSTEM = """\
You read the transcript of a short video and introduce it to the person about \
to edit its dialogue. Return `opening`: one or two plain sentences on what is \
there — who speaks and how many lines, and the one or two things worth knowing \
before deciding what to change (what is said once, what is never said, where \
the pitch is), with times as m:ss. For example: "Two people, twenty lines. The \
offer is never said; the brand name comes up once, at 0:07." Return `roles`: \
for each speaker, by the name the transcript shows, the role they play in the \
clip as a short noun phrase a person would call them by — "Customer", \
"Shopkeeper", "Presenter", "Narrator", "Host", "Guest" — and `why` in one \
short sentence. Never invent a personal name.\
"""

REVISE_SYSTEM = """\
You revise a plan of dialogue edits for a video. The plan's items are listed \
with their ids; each is one line of the transcript and the new words for it, \
with whether it is included, how it meets the picture, how it is delivered, \
and whether it has already been voiced. The user says, in their own words, \
what to change about the plan.

Return `changes`: one entry per item the instruction touches, with only the \
fields that change — `enabled` false to leave an item out (true to put it \
back), `new_text` for different words (the full line; keep it within the \
line's syllable budget), `mix` for an added line ("over": plays over the \
moving picture; "concatenate": the picture holds), `delivery` for how it is \
said ("warmer", "calmer", "more excited", "slower", "firmer", or the user's \
own words; "as spoken" to clear it). Leave an item alone unless the \
instruction is about it: items already voiced keep their takes.
Return `additions` for new changes the instruction asks for that no item \
covers, as edits on transcript lines (same rules as planning: words only, no \
label in front; `speaker` only when someone else says an added line).
`summary` is one plain sentence to the user on what you changed, e.g. "Left \
out the line at 0:17 and made the first one warmer."
If the instruction is a new goal for the whole video rather than a change to \
this plan, set `new_goal` true, leave `changes` and `additions` empty, and \
say so in `summary`.\
"""


class _Edit(BaseModel):
    line: int = Field(description="The transcript line number this change is for.")
    new_text: str = Field(description="The words to speak, and nothing else — never a speaker's name or label in front.")
    mix: Literal["replace", "over", "concatenate"]
    reason: str
    speaker: str | None = Field(default=None, description="Who says it, by their name as the transcript shows it. Needed for an added line spoken by someone other than the line it follows; null otherwise.")


class _Question(BaseModel):
    text: str
    options: list[str]
    guess: str | None


class _PlanReading(BaseModel):
    summary: str
    findings: list[str]
    question: _Question | None
    edits: list[_Edit]
    suggestions: list[_Edit]


class _Shortening(BaseModel):
    new_text: str


class _Role(BaseModel):
    speaker: str = Field(description="The speaker's name exactly as the transcript shows it.")
    role: str = Field(description="A short noun phrase for who they are in the clip: Customer, Shopkeeper, Presenter…")
    why: str


class _Reading(BaseModel):
    opening: str
    roles: list[_Role]


class _ItemChange(BaseModel):
    item_id: str
    enabled: bool | None = None
    new_text: str | None = None
    mix: Literal["over", "concatenate"] | None = None
    delivery: str | None = Field(default=None, description='How it is said; "as spoken" clears it.')


class _Revision(BaseModel):
    summary: str
    new_goal: bool = False
    changes: list[_ItemChange]
    additions: list[_Edit]


def render_plan_request(goal: str, lines: Sequence[Line], history: Sequence[str],
                        answer: tuple[str, str] | None = None) -> str:
    out = []
    if history:
        out.append("Earlier goals in this project:")
        out += [f"- {h}" for h in history]
        out.append("")
    if answer:
        out += [f"You asked: {answer[0]}", f"The user answered: {answer[1]}",
                "Plan with that answer and ask nothing more.", ""]
    out.append("Transcript (each line's syllables now, and how many its slot can hold):")
    for line in lines:
        who = f" {line.speaker}:" if line.speaker else ""
        fits = (f"  ({line.syllables} syl now, up to {line.budget} fit)"
                if line.syllables is not None and line.budget is not None else "")
        out.append(f"{line.index}. [{line.start:.1f}s]{who} {line.text}{fits}")
    out += ["", f"Goal: {goal}"]
    return "\n".join(out)


def render_read_request(lines: Sequence[Line]) -> str:
    out = ["Transcript:"]
    for line in lines:
        who = f" {line.speaker}:" if line.speaker else ""
        out.append(f"{line.index}. [{_mmss(line.start)}]{who} {line.text}")
    return "\n".join(out)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def render_revise_request(instruction: str, items: Sequence[ItemView], lines: Sequence[Line], goal: str) -> str:
    out = ["Transcript (each line's syllables now, and how many its slot can hold):"]
    for line in lines:
        who = f" {line.speaker}:" if line.speaker else ""
        fits = (f"  ({line.syllables} syl now, up to {line.budget} fit)"
                if line.syllables is not None and line.budget is not None else "")
        out.append(f"{line.index}. [{_mmss(line.start)}]{who} {line.text}{fits}")
    out += ["", f"The plan (goal: {goal}):"]
    for item in items:
        line = next((ln for ln in lines if ln.index == item.line), None)
        at = _mmss(line.start) if line else "?"
        how = ("replaces the line" if item.mix == "replace"
               else "added after, over the picture" if item.mix in ("over", "layer")
               else "added after, the picture holds")
        state = "voiced" if item.status in ("ready", "approved") else "not voiced yet"
        flags = [how, state]
        if item.delivery:
            flags.append(f"delivery: {item.delivery}")
        if not item.enabled:
            flags.append("left out")
        who = f" {item.speaker}" if item.speaker else ""
        out.append(f'{item.item_id}. line {item.line} [{at}]{who}: "{item.old_text}" → "{item.new_text}" ({"; ".join(flags)})')
    out += ["", f"The user says: {instruction}"]
    return "\n".join(out)


def to_reading(reading: _Reading, lines: Sequence[Line]) -> Reading:
    names = {line.speaker for line in lines if line.speaker}
    roles = []
    seen = set()
    for r in reading.roles:
        speaker, role = r.speaker.strip(), r.role.strip().strip('"').rstrip(".")
        if speaker in names and role and speaker not in seen:
            seen.add(speaker)
            roles.append(Role(speaker, role[:1].upper() + role[1:], r.why.strip()))
    return Reading(opening=reading.opening.strip(), roles=tuple(roles))


def to_revision(reading: _Revision, items: Sequence[ItemView], lines: Sequence[Line]) -> Revision:
    known = {i.item_id for i in items}
    names = [line.speaker for line in lines if line.speaker]
    changes = []
    for c in reading.changes:
        if c.item_id not in known:
            continue
        text = strip_label(c.new_text.strip().strip('"').strip(), names) if c.new_text else None
        delivery = (c.delivery or "").strip()
        clear = delivery.lower() in ("as spoken", "none", "clear", "default")
        changes.append(ItemChange(
            c.item_id, enabled=c.enabled, new_text=text or None, mix=c.mix,
            delivery=None if clear or not delivery else delivery, clear_delivery=clear,
        ))
    additions = to_proposal(_PlanReading(summary="", findings=[], question=None, edits=reading.additions,
                                         suggestions=[]), lines).edits
    return Revision(summary=reading.summary.strip() or "Changed the plan.", changes=tuple(changes),
                    additions=additions, new_goal=reading.new_goal)


_LABEL = re.compile(r"^\s*(?:the\s+)?([A-Za-z][\w' ]{0,30}?)\s*:\s+", re.IGNORECASE)


def strip_label(text: str, names: Sequence[str]) -> str:
    """Drop a leading "Shopkeeper:" — a script habit the model sometimes keeps,
    which would otherwise be read aloud. Only a known name, or a generic
    "speaker"/"narrator", is stripped."""
    m = _LABEL.match(text)
    if not m:
        return text
    label = m.group(1).strip().lower()
    known = {n.lower() for n in names} | {"speaker", "narrator", "voice"}
    if label in known or label.startswith("speaker "):
        return text[m.end():].strip()
    return text


def to_proposal(reading: _PlanReading, lines: Sequence[Line]) -> Proposal:
    known = {line.index for line in lines}
    names = [line.speaker for line in lines if line.speaker]

    def changes(items: list[_Edit]) -> tuple[Change, ...]:
        out = []
        for e in items:
            text = strip_label(e.new_text.strip().strip('"').strip(), names)
            speaker = (e.speaker or "").strip() or None
            if speaker and speaker.lower() not in {n.lower() for n in names}:
                speaker = None
            if e.line in known and text:
                out.append(Change(e.line, text, e.mix, e.reason.strip(), speaker))
        return tuple(out)

    question = None
    if reading.question and reading.question.text.strip() and reading.question.options:
        options = tuple(o.strip() for o in reading.question.options if o.strip())
        guess = (reading.question.guess or "").strip() or None
        question = Question(reading.question.text.strip(), options, guess if guess in options else options[0])
    return Proposal(
        summary=reading.summary.strip() or "Here's my plan.",
        edits=changes(reading.edits), suggestions=changes(reading.suggestions),
        findings=tuple(f.strip() for f in reading.findings if f.strip())[:4],
        question=question,
    )


class ClaudePlanner:
    identity = "claude"

    def __init__(
        self, api_key: str, workspace_id: str | None, *, model: str = MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)
        self._model = model

    def _parse(self, system: str, content: str, output_format, effort: str, meter: Meter | None):
        try:
            response = self._client.messages.parse(
                model=self._model, max_tokens=MAX_TOKENS, output_config={"effort": effort},
                system=system, messages=[{"role": "user", "content": content}],
                output_format=output_format,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise IntentError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise IntentConfigError(
                f"Claude refused the request ({exc.status_code}). "
                "Check ANTHROPIC_API_KEY and ANTHROPIC_WORKSPACE_ID."
            ) from None
        if meter is not None and response.usage is not None:
            meter(self._model, response.usage.input_tokens, response.usage.output_tokens)
        return response

    def plan(self, goal: str, lines: Sequence[Line], history: Sequence[str] = (),
             meter: Meter | None = None, answer: tuple[str, str] | None = None) -> Proposal:
        response = self._parse(SYSTEM, render_plan_request(goal, lines, history, answer), _PlanReading,
                               "medium", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return Proposal(summary="I can't plan that request.", edits=())
        return to_proposal(response.parsed_output, lines)

    def shorten(self, text: str, share: float, line: Line, meter: Meter | None = None) -> str | None:
        content = (f'Line: "{text}"\nIt must be spoken in about {share:.0%} of the time it takes now'
                   f" (the original line there was \"{line.text}\").")
        response = self._parse(SHORTEN_SYSTEM, content, _Shortening, "low", meter)
        if response.parsed_output is None:
            return None
        short = response.parsed_output.new_text.strip().strip('"').strip()
        return short if short and short != text else None

    def read(self, lines: Sequence[Line], meter: Meter | None = None) -> Reading:
        response = self._parse(READ_SYSTEM, render_read_request(lines), _Reading, "low", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            n = len(lines)
            return Reading(opening=f"{n} {'line' if n == 1 else 'lines'}.")
        return to_reading(response.parsed_output, lines)

    def revise(self, instruction: str, items: Sequence[ItemView], lines: Sequence[Line],
               goal: str, meter: Meter | None = None) -> Revision:
        response = self._parse(REVISE_SYSTEM, render_revise_request(instruction, items, lines, goal),
                               _Revision, "medium", meter)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return Revision(summary="I can't change the plan that way.")
        return to_revision(response.parsed_output, items, lines)
