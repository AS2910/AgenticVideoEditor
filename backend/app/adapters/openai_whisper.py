"""Real word-level transcription via OpenAI.

Model choice is not arbitrary: `whisper-1` is the only OpenAI transcription
model that accepts `response_format=verbose_json`, which is what carries word
timestamps. The `gpt-4o-transcribe` family rejects verbose_json outright
("use 'json' or 'text' instead"), so it cannot produce the word timings the
timeline is built on. Verified against the live API on 2026-09-23.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

import httpx

from app.adapters.base import VendorError
from app.domain.models import Source, Statement, Transcript, Word
from app.media import ffmpeg

MODEL = "whisper-1"
ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"

# The whole response for a short clip is small; the ceiling is for slow uploads
# of a 3-minute source.
DEFAULT_TIMEOUT = 120.0


class TranscriptionError(VendorError):
    """The vendor call failed or returned something unusable."""


def to_transcript(payload: dict) -> Transcript:
    """Turn a verbose_json response into the domain Transcript."""
    words: list[Word] = []
    for raw in payload.get("words") or []:
        text = (raw.get("word") or "").strip()
        if not text:
            # Whisper emits an empty word where it stripped a symbol — the '%'
            # in "20%" arrives as '' holding a real time slot. Dropping it
            # leaves a gap, which snapping tolerates; a blank timeline cell it
            # would not.
            continue
        try:
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        words.append(Word(text=text, start=start, end=end))
    statements = []
    for raw in payload.get("segments") or []:
        text = (raw.get("text") or "").strip()
        try:
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if text and end > start:
            statements.append(Statement(text=text, start=start, end=end))
    return Transcript(words=tuple(words), statements=tuple(statements))


def _post(audio_path: Path, api_key: str, timeout: float) -> dict:
    with audio_path.open("rb") as handle:
        response = httpx.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (audio_path.name, handle, "audio/wav")},
            data={
                "model": MODEL,
                "response_format": "verbose_json",
                # Words for the timeline and edit boundaries; segments for the
                # transcript's statements (they keep Whisper's punctuation).
                "timestamp_granularities[]": ["word", "segment"],
            },
            timeout=timeout,
        )
    if response.status_code != 200:
        raise TranscriptionError(
            f"OpenAI transcription failed ({response.status_code}): "
            f"{response.text[:300]}"
        )
    return response.json()


class WhisperTranscriptionAdapter:
    """Extracts the source's audio, sends it to OpenAI, returns word timings.

    `post` is injectable so tests can replay a recorded response instead of
    calling the vendor — the suite never spends money or needs a network.
    """

    def __init__(
        self,
        api_key: str,
        *,
        post: Callable[[Path, str, float], dict] = _post,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._post = post
        self._timeout = timeout

    def transcribe(self, source: Source) -> Transcript:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            try:
                ffmpeg.extract_audio(source.media.path, audio)
            except ffmpeg.FFmpegError as exc:
                raise TranscriptionError(
                    "Could not extract audio from the source video."
                ) from exc
            payload = self._post(audio, self._api_key, self._timeout)
        return to_transcript(payload)
