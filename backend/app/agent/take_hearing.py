"""9a: hearing a take before its words are checked (A3).

The voice vendor's word alignment repeats the text it was sent, so a take
that mispronounces a glossary term still "says" it there. This runs the
transcriber (Whisper) on the take itself and returns what was heard, so the
check in `word_rules.check_take` compares the project's words with the sound.

    hear_take(video_id, candidate, *, transcriber, label, ledger, enabled) -> [words] | None

None means "not heard": the check then falls back to the vendor's words.
That is the case when the transcriber is not a real one (the mock would
hear its canned words in every take), when `projects.consistency` is off
for the video's owner, when the take has no audio, or when the call fails.
A heard take is charged to the ledger by the minute, like every Whisper call.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.domain.models import Source
from app.usage import WHISPER_USD_PER_MINUTE

log = logging.getLogger(__name__)

WHAT = "take_check"   # the ledger line a heard take is charged under


def hear_take(video_id: str, candidate: Any, *, transcriber: Any, label: str, ledger: Any,
              enabled: Callable[[], bool]) -> list[str] | None:
    if not label.startswith("openai") or not hasattr(transcriber, "hear"):
        return None
    audio = getattr(candidate, "audio", None)
    if audio is None or not getattr(audio, "path", None):
        return None
    try:
        if not enabled():
            return None
    except Exception:  # noqa: BLE001 - a flag read failing leaves the old check in place
        return None
    duration = float(getattr(audio, "duration", 0.0) or 0.0)
    source = Source(project_id=video_id, filename="take.wav", duration=duration, media=audio)
    try:
        words = list(transcriber.hear(source))
    except Exception as exc:  # noqa: BLE001 - a failed hearing never fails the take
        log.warning("hearing take %s failed: %s", getattr(candidate, "candidate_id", "?"), exc)
        return None
    minutes = duration / 60
    ledger.record(video_id, "openai", WHAT, minutes, "minutes", minutes * WHISPER_USD_PER_MINUTE)
    return words
