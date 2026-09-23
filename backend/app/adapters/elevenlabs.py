"""Real speech via ElevenLabs text-to-speech, in a stock voice (Phase 4a).

The free tier refuses voice cloning, so this speaks the new line in a premade
voice rather than the speaker's own — `identity = "stock"` makes the pipeline
say so on the candidate. Phase 4b swaps `voice_id` for a clone.

Facts this relies on were measured against the live API on 2026-09-23 (see the
Phase 4a plan's spike results): `pcm_24000` is allowed on the free tier, the
`previous_text`/`next_text` context is accepted by multilingual_v2 and flash but
refused by eleven_v3, and only `text` is billed — the context is free.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from app.adapters.base import VendorError
from app.budget import VoiceBudget
from app.domain.models import EditPlan, MediaArtifact, Source, Transcript
from app.errors import NonRetryableError
from app.media import ffmpeg
from app.store.artifacts import ArtifactStore

ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
OUTPUT_FORMAT = "pcm_24000"
SAMPLE_RATE = 24000
DEFAULT_TIMEOUT = 60.0

# Longest context sent either side of the edit. Enough for a sentence of
# prosody; more buys nothing and slows the request.
CONTEXT_CHARS = 200

# Character-cost multipliers, as reported by GET /v1/models. Unlisted models
# bill at 1.0, which over-estimates rather than under-estimates spend.
_COST_MULTIPLIER = {
    "eleven_flash_v2_5": 0.5,
    "eleven_turbo_v2_5": 0.5,
    "eleven_flash_v2": 0.5,
    "eleven_turbo_v2": 0.5,
}

# (status, body bytes, body text)
PostFn = Callable[[str, dict, str, float], tuple[int, bytes, str]]


class VoiceError(VendorError):
    """ElevenLabs failed in a way worth retrying: rate limit, outage, network."""


class VoiceConfigError(NonRetryableError):
    """ElevenLabs refused the request itself: key, quota, or a bad parameter."""


def billed_characters(text: str, model: str) -> int:
    return math.ceil(len(text) * _COST_MULTIPLIER.get(model, 1.0))


def _context(words: list[str], from_end: bool) -> str:
    """Join whole words up to CONTEXT_CHARS, keeping those nearest the edit."""
    picked: list[str] = []
    length = 0
    for word in (reversed(words) if from_end else words):
        extra = len(word) + (1 if picked else 0)
        if length + extra > CONTEXT_CHARS:
            break
        picked.append(word)
        length += extra
    return " ".join(reversed(picked) if from_end else picked)


def to_request(plan: EditPlan, transcript: Transcript | None, model: str) -> dict:
    body: dict = {"text": plan.new_text, "model_id": model}
    if transcript is None:
        return body
    start, end = plan.selection.start, plan.selection.end
    before = [w.text for w in transcript.words if w.end <= start]
    after = [w.text for w in transcript.words if w.start >= end]
    if before:
        body["previous_text"] = _context(before, from_end=True)
    if after:
        body["next_text"] = _context(after, from_end=False)
    return body


def _post(voice_id: str, body: dict, api_key: str, timeout: float) -> tuple[int, bytes, str]:
    try:
        response = httpx.post(
            ENDPOINT.format(voice_id=voice_id),
            params={"output_format": OUTPUT_FORMAT},
            headers={"xi-api-key": api_key},
            json=body,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        # The exception text is dropped: transport errors can echo request
        # details, and the key is one of them.
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    ok = response.status_code == 200
    return response.status_code, response.content if ok else b"", "" if ok else response.text


def _raise_for(status: int, text: str) -> None:
    if status == 429 or status >= 500:
        raise VoiceError(f"ElevenLabs is unavailable right now ({status}).")
    lowered = text.lower()
    if "quota" in lowered:
        raise VoiceConfigError("The ElevenLabs quota for this month is used up.")
    if status in (401, 403):
        raise VoiceConfigError(
            f"ElevenLabs rejected the API key ({status}). Check ELEVENLABS_API_KEY."
        )
    detail = text[:200]
    raise VoiceConfigError(f"ElevenLabs refused the request ({status}): {detail}")


class ElevenLabsVoiceAdapter:
    identity = "stock"

    def __init__(
        self,
        api_key: str,
        store: ArtifactStore,
        budget: VoiceBudget,
        *,
        model: str,
        voice_id: str,
        post: PostFn = _post,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._store = store
        self._budget = budget
        self._model = model
        self._voice_id = voice_id
        self._post = post
        self._timeout = timeout

    def cost_of(self, plan: EditPlan) -> int:
        return billed_characters(plan.new_text, self._model)

    def synthesize(
        self, source: Source, plan: EditPlan, transcript: Transcript | None = None,
    ) -> MediaArtifact:
        # Charged per attempt, before the call: a retry is real spend.
        self._budget.charge(source.project_id, self.cost_of(plan))

        body = to_request(plan, transcript, self._model)
        status, audio, text = self._post(self._voice_id, body, self._api_key, self._timeout)
        if status != 200:
            _raise_for(status, text.replace(self._api_key, "***"))

        target = plan.selection.end - plan.selection.start
        with tempfile.TemporaryDirectory() as tmp:
            raw, _ = ffmpeg.pcm_to_wav(audio, Path(tmp) / "raw.wav", SAMPLE_RATE)
            fitted, duration = ffmpeg.fit_duration(raw, Path(tmp) / "voice.wav", target)
            return self._store.put_file(
                source.project_id, fitted, kind="audio", container="wav", duration=duration,
            )
