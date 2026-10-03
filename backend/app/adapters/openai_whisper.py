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

import re

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


# Whisper invents speech where there is none — wind, music, room noise — and
# it invents the same few phrases, the sign-offs of the videos it learnt from.
# A segment is dropped when Whisper's own numbers say it probably is not speech,
# or when it is one of these phrases and Whisper is not sure of it either.
NO_SPEECH_PROB_MAX = 0.6        # Whisper's own "this is not speech" probability
AVG_LOGPROB_MIN = -1.0          # how unlikely the words were, per token
COMPRESSION_RATIO_MAX = 2.4     # repeated text compresses too well
KNOWN_PHRASE_NO_SPEECH = 0.2    # a known phrase needs this much doubt to go
HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "thank you for watching my video",
    "thank you so much for watching", "thanks for watching bye", "see you in the next video",
    "see you next time", "please subscribe", "like and subscribe", "subscribe to my channel",
    "thank you", "thanks", "bye", "goodbye", "you", "the end", "music", "applause",
    "subtitles by the amara org community", "www mooji org",
}
# Speech has to stand out from the recording's own noise by this much.
SPEECH_ABOVE_FLOOR_DB = 8.0

_PUNCT = re.compile(r"[^\w\s]")


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub("", text.lower())).strip()


def doubtful(segment: dict) -> str | None:
    """Why a segment looks invented, or None when it looks like real speech."""
    nsp = segment.get("no_speech_prob")
    if nsp is not None and float(nsp) > NO_SPEECH_PROB_MAX:
        return f"no_speech_prob {float(nsp):.2f}"
    lp = segment.get("avg_logprob")
    if lp is not None and float(lp) < AVG_LOGPROB_MIN:
        return f"avg_logprob {float(lp):.2f}"
    cr = segment.get("compression_ratio")
    if cr is not None and float(cr) > COMPRESSION_RATIO_MAX:
        return f"compression_ratio {float(cr):.2f}"
    if _normal(segment.get("text") or "") in HALLUCINATIONS and (nsp is None or float(nsp) > KNOWN_PHRASE_NO_SPEECH):
        return "a phrase Whisper invents on silence"
    return None


def to_transcript(payload: dict) -> Transcript:
    """Turn a verbose_json response into the domain Transcript, leaving out
    the segments (and their words) that Whisper most likely made up."""
    dropped: list[tuple[float, float]] = []
    for raw in payload.get("segments") or []:
        why = doubtful(raw)
        if why:
            try:
                dropped.append((float(raw["start"]), float(raw["end"])))
            except (KeyError, TypeError, ValueError):
                continue
            log.info("dropped a doubtful segment %r: %s", (raw.get("text") or "").strip(), why)

    def invented(start: float, end: float) -> bool:
        return any(start < b and a < end for a, b in dropped)

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
        if invented(start, end):
            continue
        words.append(Word(text=text, start=start, end=end))
    statements = []
    for raw in payload.get("segments") or []:
        text = (raw.get("text") or "").strip()
        try:
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if text and end > start and not invented(start, end):
            statements.append(Statement(text=text, start=start, end=end))
    return Transcript(words=tuple(words), statements=tuple(statements))


def without_silent_speech(transcript: Transcript, audio_path: Path) -> Transcript:
    """Drop statements whose audio has no speech in it: nothing stands out
    from the recording's own noise floor there. Whisper's numbers catch most
    inventions; this catches the confident ones over wind or music."""
    if not transcript.statements:
        return transcript
    from app.continuity import signals
    try:
        audio = signals.load(audio_path)
    except Exception:  # noqa: BLE001 - a failed measurement must not fail the upload
        return transcript
    floor = signals.noise_floor_db(audio)
    kept, dropped = [], []
    for st in transcript.statements:
        span = audio[int(st.start * signals.RATE): int(st.end * signals.RATE)]
        level = signals.speech_level_db(span) if len(span) else None
        if level is None or level - floor < SPEECH_ABOVE_FLOOR_DB:
            dropped.append(st)
            log.info("dropped %r: no speech energy there (%s dB over a %.0f dB floor)",
                     st.text, "none" if level is None else f"{level - floor:.0f}", floor)
        else:
            kept.append(st)
    if not dropped:
        return transcript
    words = tuple(w for w in transcript.words
                  if not any(w.start < d.end and d.start < w.end for d in dropped))
    return Transcript(words=words, statements=tuple(kept))


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
        # Drop statements with no speech energy behind them. Off only in
        # tests that replay a recording over a silent fixture.
        screen_silence: bool = True,
    ) -> None:
        self._api_key = api_key
        self._post = post
        self._post_diarize = post_diarize
        self._timeout = timeout
        self._screen_silence = screen_silence

    def transcribe(self, source: Source) -> Transcript:
        """Words and statements, labelled by speaker when diarization works.
        Diarization failing never fails the upload: the words stand alone."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            transcript = to_transcript(self._post(audio, self._api_key, self._timeout))
            if self._screen_silence:
                transcript = without_silent_speech(transcript, audio)
            if not transcript.words:
                return transcript
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
