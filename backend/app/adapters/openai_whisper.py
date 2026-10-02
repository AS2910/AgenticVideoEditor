"""Real word-level transcription via OpenAI.

Model choice is not arbitrary: `whisper-1` is the only OpenAI transcription
model that accepts `response_format=verbose_json`, which is what carries word
timestamps. The `gpt-4o-transcribe` family rejects verbose_json outright
("use 'json' or 'text' instead"), so it cannot produce the word timings the
timeline is built on. Verified against the live API on 2026-09-23.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from app.adapters.base import VendorError
from app.domain.models import Source, Statement, Transcript, Word
from app.domain.transcript import assign_speakers
from app.media import ffmpeg

MODEL = "whisper-1"
ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"

# The whole response for a short clip is small; the ceiling is for slow uploads
# of a 3-minute source.
DEFAULT_TIMEOUT = 120.0

log = logging.getLogger(__name__)


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


# Who speaks when (Phase 11). A second call: the diarizing model gives speaker
# turns but no word timings, so Whisper still provides the words. Chosen over
# ElevenLabs Scribe to keep the free tier's credits for speech (plan, Phase 11).
DIARIZE_MODEL = "gpt-4o-transcribe-diarize"

Turn = tuple[str, float, float]  # (speaker, start, end)


def to_turns(payload: dict) -> list[Turn]:
    turns = []
    for raw in payload.get("segments") or []:
        try:
            speaker, start, end = str(raw["speaker"]), float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            turns.append((speaker, start, end))
    return turns


def _post_diarize(audio_path: Path, api_key: str, timeout: float) -> dict:
    try:
        with audio_path.open("rb") as handle:
            response = httpx.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, handle, "audio/wav")},
                data={
                    "model": DIARIZE_MODEL,
                    "response_format": "diarized_json",
                    "chunking_strategy": "auto",
                },
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Could not reach OpenAI ({type(exc).__name__}).") from None
    if response.status_code != 200:
        raise TranscriptionError(
            f"OpenAI diarization failed ({response.status_code}): {response.text[:300]}"
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
        post_diarize: Callable[[Path, str, float], dict] = _post_diarize,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._post = post
        self._post_diarize = post_diarize
        self._timeout = timeout

    def transcribe(self, source: Source) -> Transcript:
        """Words and statements, labelled by speaker when diarization works.
        Diarization failing never fails the upload: the words stand alone."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            transcript = to_transcript(self._post(audio, self._api_key, self._timeout))
            try:
                turns = to_turns(self._post_diarize(audio, self._api_key, self._timeout))
            except TranscriptionError as exc:
                log.warning("diarization failed for %s: %s", source.project_id, exc)
                return transcript
        return assign_speakers(transcript, turns)

    def diarize(self, source: Source) -> list[Turn]:
        """Speaker turns alone — for projects transcribed before Phase 11."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            return to_turns(self._post_diarize(audio, self._api_key, self._timeout))

    def _audio(self, source: Source, tmp: Path) -> Path:
        audio = tmp / "audio.wav"
        try:
            ffmpeg.extract_audio(source.media.path, audio)
        except ffmpeg.FFmpegError as exc:
            raise TranscriptionError("Could not extract audio from the source video.") from exc
        return audio
