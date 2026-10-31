"""Voice consent V1, step 4: the check model's pass over lines to be voiced.

One structured-output call over every line of a video that the rules let
through (app.safety.line_rules), with the video's brief and its other lines as
context, on the small model (`settings.check_model`, Haiku 5.5), returning
{verdict, categories, reason} per line. Charged through the meter like every
other Claude call, so it lands in Usage under the video.
"""
from __future__ import annotations

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.adapters.claude_planner import PlannerConfigError, PlannerError
from app.orchestrator.meter import Meter

PROMPT_VERSION = "lines-2026-10-31.3"
LINES_MAX_TOKENS = 4096
# A line check sits in front of a take: a short timeout, one retry (the guard decides when it fails).
TIMEOUT_S, RETRIES = 12.0, 1
# Thinking stays adaptive by default: the eval found it off 0.1 s to 0.4 s faster at p95 but with false
# blocks on ordinary lines (2 in 100 against none). AVE_LINE_CHECK_THINKING=off trades the other way.
THINKING_OFF = os.environ.get("AVE_LINE_CHECK_THINKING", "").strip().lower() == "off"

Category = Literal["fraud", "impersonation", "political", "sexual", "minors", "hate", "claims", "unclear"]

SYSTEM = """\
You check lines that a video editor is about to speak in a synthetic voice, \
for ads and short videos made in India and elsewhere. Lines may be in English, \
Hindi (Devanagari) or Hinglish (Hindi in Latin letters). For each line return \
a verdict:

block, with the categories that apply, when the line itself does one of these:
- fraud: asks the listener for an OTP, PIN, password, CVV, card, UPI or bank \
details, or pushes them to transfer or pay money urgently to someone (a scam \
script: "your account will be blocked", "you won a lottery, pay the fee").
- impersonation: the speaker claims to be a named real person (a celebrity, a \
politician) or an official: the police, a court, a bank, the RBI, tax or \
customs officers, a government body.
- political: endorses or attacks a political party, candidate or politician, \
or tells people how or whether to vote.
- sexual: sexual or explicit content. Add "minors" as well when any sexual \
content involves a child or a minor.
- hate: slurs, threats of violence, telling a group of people to die or leave, \
targeted harassment or abuse of a person.

review, with the category, when:
- claims: a claim to cure or treat a disease or condition ("cures diabetes", \
"no more BP tablets"), a promise of guaranteed or risk-free money ("guaranteed \
returns", "double your money in a month"), or a miracle result ("lose 10 kg in \
a week"). Ordinary product claims are not this: "kills 99.9% of germs", \
"clinically tested", "gentle on skin", a bank's or lender's stated interest \
rate, "fastest delivery in town" all pass.
- unclear: you are not sure whether it should be blocked.

pass for everything else. Most lines are ordinary ad copy and pass: offers, \
discounts, prices, product benefits, store timings, delivery, calls to action \
("order now", "download the app", "pay with UPI and get cashback"), \
testimonials from ordinary customers, festival greetings, and safety advice \
such as "never share your OTP with anyone". Mentioning a bank, a card, UPI or \
a brand is not fraud; a bank promoting its own product is not impersonation. \
Judge each line on its own words, using its neighbours and the brief only to \
understand it. Write `reason` as one short plain sentence, empty for a pass. \
Return one result for every line id you are given. Never use em dashes."""


class LineResult(BaseModel):
    id: str
    verdict: Literal["pass", "review", "block"]
    categories: list[Category] = Field(default_factory=list)
    reason: str = ""


class LineResults(BaseModel):
    lines: list[LineResult] = Field(default_factory=list)


def _effort(model: str) -> dict:
    """Low effort: a short classification, on the latency path of every take (thinking off only
    when AVE_LINE_CHECK_THINKING=off; Haiku 5.5 takes that at low effort; DECISIONS.md step 4)."""
    if model.startswith("claude-haiku-4"):
        return {}
    return {"output_config": {"effort": "low"}, **({"thinking": {"type": "disabled"}} if THINKING_OFF else {})}


def prompt(lines: list[dict], context: dict | None = None) -> str:
    """The user turn: the brief, the video's other lines, then the lines to check by id."""
    context = context or {}
    parts = []
    if context.get("brief"):
        parts.append(f"The brief: {context['brief']}")
    if context.get("neighbours"):
        parts.append("Other lines in this video, in order:\n" + "\n".join(f"- {t}" for t in context["neighbours"]))
    parts.append("Check these lines (JSON, by id):\n" + json.dumps([{"id": ln["id"], "text": ln["text"]} for ln in lines],
                                                                    ensure_ascii=False))
    return "\n\n".join(parts)


class ClaudeLineReader:
    def __init__(self, api_key: str | None, workspace_id: str | None, *, model: str,
                 client: anthropic.Anthropic | None = None) -> None:
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers, timeout=TIMEOUT_S,
                                                     max_retries=RETRIES)
        self.model = model

    def read(self, lines: list[dict], context: dict | None = None, meter: Meter | None = None) -> dict[str, dict]:
        """{id: {verdict, categories, reason}} for the lines given ({id, text}); an id the
        model left out is missing (the caller treats it as unsure). Raises PlannerError
        or PlannerConfigError when the call fails."""
        try:
            response = self._client.messages.parse(
                model=self.model, max_tokens=LINES_MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": prompt(lines, context)}], **_effort(self.model),
                output_format=LineResults,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise PlannerError(f"Claude is unavailable right now ({type(exc).__name__}).") from None
        except anthropic.APIStatusError as exc:
            raise PlannerConfigError(f"Claude refused the request ({exc.status_code}).") from None
        if meter is not None and getattr(response, "usage", None) is not None:
            meter(self.model, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            # A refusal on a line check is itself a signal: every line is unsure (held for a person).
            return {ln["id"]: {"verdict": "review", "categories": ["unclear"],
                               "reason": "The check model would not read this line."} for ln in lines}
        return {r.id: {"verdict": r.verdict, "categories": list(dict.fromkeys(r.categories)), "reason": r.reason.strip()}
                for r in response.parsed_output.lines}
