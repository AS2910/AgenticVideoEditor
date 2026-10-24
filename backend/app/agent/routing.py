"""Cost 1b: a how-do-I question goes to the small model.

A turn whose words only ask how Voltage works ("How do I make a vertical
version?") needs the help articles and a few sentences, not the planner: it
runs on the small model (settings.question_model) with the read-only tools.
Two gates, cheapest first: the words must look like a question (no call at
all for "Make it 30% off"), then the small model says whether they are only a
question about the app, or a request for the video put as one ("Can you make
it 30% off?"), which stays with the planner. Anything unclear stays too.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Sequence

from pydantic import BaseModel

log = logging.getLogger(__name__)

# The read-only tools a question turn may use.
QUESTION_TOOLS = ("search_help", "project_state", "read_transcript", "look_at_frames")
_QUESTION = re.compile(r"^\s*(how|what|where|why|when|which|is|are|can|could|does|do|will|should)\b.*\?\s*$",
                       re.IGNORECASE | re.DOTALL)
MAX_CHARS = 400

CLASSIFY_SYSTEM = """You sort one message a user typed into a video dialogue editor called Voltage.
Answer question=true only when the message asks how the app works, what a feature does, or where
something is, and asks for no change to this video. A request for a change put as a question
("can you make it 30% off?", "could you add music?") is question=false. When unsure, question=false."""


class _Sorted(BaseModel):
    question: bool


def looks_like_question(text: str) -> bool:
    return len(text) <= MAX_CHARS and bool(_QUESTION.match(text))


def has_compaction(history: Sequence[dict]) -> bool:
    """A thread the planner compacted carries blocks only its beta reads."""
    return any(isinstance(b, dict) and b.get("type") == "compaction"
               for m in history for b in (m.get("content") if isinstance(m.get("content"), list) else ()))


def is_question(client, model: str, text: str, meter: Callable[[str, int, int, int, int], None] | None = None) -> bool:
    """Whether `text` only asks how the app works. Any failure says no."""
    if not looks_like_question(text):
        return False
    try:
        response = client.messages.parse(model=model, max_tokens=1024, system=CLASSIFY_SYSTEM,
                                         messages=[{"role": "user", "content": text}], output_format=_Sorted,
                                         output_config={"effort": "low"})
    except Exception as exc:  # noqa: BLE001 - the planner takes the turn
        log.warning("question routing failed: %s", str(exc)[:160])
        return False
    usage = getattr(response, "usage", None)
    if meter is not None and usage is not None:
        meter(model, usage.input_tokens, usage.output_tokens, getattr(usage, "cache_read_input_tokens", 0) or 0,
              getattr(usage, "cache_creation_input_tokens", 0) or 0)
    parsed = getattr(response, "parsed_output", None)
    return bool(parsed and parsed.question)
