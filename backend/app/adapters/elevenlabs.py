"""Real speech via ElevenLabs text-to-speech (Phase 4a, 15a).

A line is spoken in a premade voice unless the speaker has a clone (15a): an
instant clone made once from their own speech and reused by every later edit.
`identity_for(plan)` says which, per take, so the pipeline labels a stock voice
and only a stock voice — the speaker's own is never passed off as stock, nor
the reverse.

Facts this relies on were measured against the live API on 2026-09-23 (see the
Phase 4a plan's spike results): `pcm_24000` is allowed on the free tier, the
`previous_text`/`next_text` context is accepted by multilingual_v2 and flash but
refused by eleven_v3, and only `text` is billed — the context is free.
"""
from __future__ import annotations

import base64
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from app.adapters.base import VendorError
from app.budget import VoiceBudget
from app.domain.models import Word, EditPlan, MediaArtifact, Source, Transcript
from app.errors import NonRetryableError
from app.media import ffmpeg, fit
from app.store.artifacts import ArtifactStore

ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# 15a: an instant voice clone is made from one WAV of the speaker and deleted
# with the project (withdrawing consent leaves nothing of them at the vendor).
# 15b: the Voice Changer re-voices a finished take into the clone, keeping the
# take's own timing and delivery. Billed by the second of audio (about 1,000
# credits a minute), against the same budget the characters are.
STS_ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}"
STS_MODEL = "eleven_multilingual_sts_v2"
STS_CHARS_PER_SECOND = 17
ADD_VOICE_ENDPOINT = "https://api.elevenlabs.io/v1/voices/add"
VOICE_ENDPOINT = "https://api.elevenlabs.io/v1/voices/{voice_id}"
# P-3: the same call, answered as JSON with the audio in base64 and a time for
# every character, from which the take's own word times are read.
TIMESTAMPS_ENDPOINT = ENDPOINT + "/with-timestamps"
VOICES_ENDPOINT = "https://api.elevenlabs.io/v2/voices"
# ElevenLabs voice ids: 20 alphanumerics. Anything else (e.g. the UI's legacy
# "speaker-1") means "the configured default voice".
_VOICE_ID = re.compile(r"[A-Za-z0-9]{20}")
OUTPUT_FORMAT = "pcm_24000"
SAMPLE_RATE = 24000
DEFAULT_TIMEOUT = 60.0

# Longest context sent either side of the edit. Enough for a sentence of
# prosody; more buys nothing and slows the request.
CONTEXT_CHARS = 200
# The model's own speed control (Phase 14): applied at generation, which
# sounds better than stretching afterwards. These are the API's limits.
SPEED_MIN, SPEED_MAX = 0.7, 1.2

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
# (api key, name, wav bytes, timeout) -> (status, new voice id, body text)
AddVoiceFn = Callable[[str, str, bytes, float], tuple[int, str, str]]
# (api key, voice id, wav bytes, timeout) -> (status, pcm bytes, body text)
ConvertFn = Callable[[str, str, bytes, float], tuple[int, bytes, str]]
# (api key, voice id, timeout) -> (status, body text)
DeleteVoiceFn = Callable[[str, str, float], tuple[int, str]]


class VoiceError(VendorError):
    """ElevenLabs failed in a way worth retrying: rate limit, outage, network."""


class VoiceConfigError(NonRetryableError):
    """ElevenLabs refused the request itself: key, quota, or a bad parameter."""


def to_voice(raw: dict) -> dict:
    labels = raw.get("labels") or {}
    return {
        "voice_id": raw["voice_id"],
        # Names arrive as "Brian - Deep, Resonant and Comforting".
        "name": raw["name"].split(" - ")[0].strip(),
        "description": raw["name"].split(" - ", 1)[1].strip() if " - " in raw["name"] else "",
        "gender": labels.get("gender"),
        "accent": labels.get("accent"),
        "age": labels.get("age"),
    }


def _get_voices(api_key: str, timeout: float) -> list[dict]:
    try:
        response = httpx.get(
            VOICES_ENDPOINT, params={"voice_type": "default", "page_size": 100},
            headers={"xi-api-key": api_key}, timeout=timeout,
        )
    except httpx.HTTPError:
        raise VoiceError("Could not reach ElevenLabs to list voices.") from None
    if response.status_code != 200:
        _raise_for(response.status_code, response.text.replace(api_key, "***"))
    return [to_voice(v) for v in response.json().get("voices", [])]


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


# How a delivery is asked of the model (UX-1). Stability low = more varied,
# expressive; style high = more exaggerated. Measured by ear on multilingual_v2.
DELIVERY_SETTINGS: dict[str, dict] = {
    "warmer": {"stability": 0.45, "style": 0.35},
    "more excited": {"stability": 0.3, "style": 0.65},
    "calmer": {"stability": 0.8, "style": 0.1},
    "slower": {"speed": 0.9},
    "firmer": {"stability": 0.6, "style": 0.3},
}


def to_request(plan: EditPlan, transcript: Transcript | None, model: str, speed: float = 1.0) -> dict:
    body: dict = {"text": plan.new_text, "model_id": model}
    settings: dict = dict(DELIVERY_SETTINGS.get((plan.delivery or "").lower(), {}))
    if abs(speed - 1.0) > 1e-3:
        settings["speed"] = round(min(SPEED_MAX, max(SPEED_MIN, speed * settings.get("speed", 1.0))), 2)
    if settings:
        body["voice_settings"] = settings
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
            TIMESTAMPS_ENDPOINT.format(voice_id=voice_id),
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


def words_from_alignment(alignment: dict | None) -> tuple[Word, ...]:
    """The take's words with their times, folded from the vendor's
    per-character alignment: a word is a maximal run of non-space characters,
    starting when its first character does and ending with its last."""
    if not alignment:
        return ()
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[Word] = []
    text, start, end = "", None, None
    for ch, a, b in zip(chars, starts, ends):
        if ch.isspace():
            if text:
                words.append(Word(text, round(start, 4), round(end, 4)))
            text, start, end = "", None, None
            continue
        text += ch
        start = a if start is None else start
        end = b
    if text:
        words.append(Word(text, round(start, 4), round(end, 4)))
    return tuple(words)


def decode_response(content: bytes) -> tuple[bytes, tuple[Word, ...]]:
    """The audio and words in a 200 response: the with-timestamps JSON, or raw
    PCM when the response is the audio itself (a recording, a stand-in)."""
    if content[:1] == b"{":
        try:
            payload = json.loads(content)
        except ValueError:
            return content, ()
        if isinstance(payload, dict) and "audio_base64" in payload:
            audio = base64.b64decode(payload["audio_base64"])
            return audio, words_from_alignment(payload.get("alignment") or payload.get("normalized_alignment"))
    return content, ()


_MISSING_PERMISSION = re.compile(r"missing the permission (\w+)")


def _raise_for(status: int, text: str) -> None:
    if status == 429 or status >= 500:
        raise VoiceError(f"ElevenLabs is unavailable right now ({status}).")
    lowered = text.lower()
    # A key made with limited access answers 401 and names what it lacks.
    missing = _MISSING_PERMISSION.search(text)
    if missing:
        raise VoiceConfigError(
            f"The ElevenLabs key is missing the {missing.group(1)} permission. "
            "Allow it on the key (ElevenLabs → Developers → API keys)."
        )
    if "voice_limit" in lowered or "maximum amount of custom voices" in lowered:
        raise VoiceConfigError("This ElevenLabs plan has no voice slot left for another clone.")
    if "quota" in lowered:
        raise VoiceConfigError("The ElevenLabs quota for this month is used up.")
    if status in (401, 403):
        raise VoiceConfigError(
            f"ElevenLabs rejected the API key ({status}). Check ELEVENLABS_API_KEY."
        )
    detail = text[:200]
    raise VoiceConfigError(f"ElevenLabs refused the request ({status}): {detail}")


def _add_voice(api_key: str, name: str, wav: bytes, timeout: float) -> tuple[int, str, str]:
    try:
        response = httpx.post(
            ADD_VOICE_ENDPOINT,
            headers={"xi-api-key": api_key},
            data={"name": name, "remove_background_noise": "true",
                  "description": "Made by Voltage from the speaker's own speech, with consent."},
            files={"files": ("reference.wav", wav, "audio/wav")},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    if response.status_code != 200:
        return response.status_code, "", response.text
    try:
        return 200, str(response.json()["voice_id"]), ""
    except (ValueError, KeyError):
        return 502, "", "ElevenLabs answered without a voice id."


def _convert(api_key: str, voice_id: str, wav: bytes, timeout: float) -> tuple[int, bytes, str]:
    try:
        response = httpx.post(
            STS_ENDPOINT.format(voice_id=voice_id),
            params={"output_format": OUTPUT_FORMAT},
            headers={"xi-api-key": api_key},
            data={"model_id": STS_MODEL, "remove_background_noise": "true"},
            files={"audio": ("take.wav", wav, "audio/wav")},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    ok = response.status_code == 200
    return response.status_code, response.content if ok else b"", "" if ok else response.text


def _delete_voice(api_key: str, voice_id: str, timeout: float) -> tuple[int, str]:
    try:
        response = httpx.delete(
            VOICE_ENDPOINT.format(voice_id=voice_id), headers={"xi-api-key": api_key}, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    return response.status_code, response.text


class ElevenLabsVoiceAdapter:
    # What a take is by default; `identity_for` says what *this* take is.
    identity = "stock"
    can_clone = True

    def __init__(
        self,
        api_key: str,
        store: ArtifactStore,
        budget: VoiceBudget,
        *,
        model: str,
        voice_id: str,
        post: PostFn = _post,
        get_voices: Callable[[str, float], list[dict]] = _get_voices,
        add_voice: AddVoiceFn = _add_voice,
        delete_voice: DeleteVoiceFn = _delete_voice,
        convert: ConvertFn = _convert,
        timeout: float = DEFAULT_TIMEOUT,
        takes_per_line: int = 1,
        fit_tolerance: float = fit.DEFAULT_TOLERANCE,
        flex_max: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._store = store
        self._budget = budget
        self._model = model
        self._voice_id = voice_id
        self._post = post
        self._get_voices = get_voices
        self._add_voice = add_voice
        self._delete_voice = delete_voice
        self._convert = convert
        # Voice ids known to be a speaker's own clone, so a take in one is
        # labelled "clone" (set by whoever resolves the voice, before synthesis).
        self._clones: set[str] = set()
        self._voices: list[dict] | None = None
        self._timeout = timeout
        # A paid take that did not fit its selection, kept so that when the
        # user answers how to place it, that same take is used — the question
        # costs nothing, and they hear the line they were asked about.
        self._held: dict[str, tuple[bytes, tuple[Word, ...]]] = {}
        self._takes = max(1, takes_per_line)
        self._tolerance = fit_tolerance
        self._flex_max = flex_max
        # What was done to the last line to make it fit, in words.
        self.last_notes: list[str] = []
        # The last take's own word times, at their fitted positions (P-3).
        self.last_words: tuple[Word, ...] = ()

    def cost_of(self, plan: EditPlan) -> int:
        return billed_characters(plan.new_text, self._model)

    @property
    def default_voice(self) -> str:
        return self._voice_id

    def voices(self) -> list[dict]:
        """The premade voices, fetched once. Listing is free."""
        if self._voices is None:
            self._voices = self._get_voices(self._api_key, self._timeout)
        return self._voices

    def voice_for(self, plan: EditPlan) -> str:
        """The voice an edit asked for, or the configured default."""
        wanted = plan.voice_profile_id
        return wanted if _VOICE_ID.fullmatch(wanted) else self._voice_id

    # ── clones (15a) ──

    def register_clone(self, voice_id: str) -> None:
        self._clones.add(voice_id)

    def identity_for(self, plan: EditPlan) -> str:
        """"clone" when this take is spoken in a speaker's own cloned voice."""
        return "clone" if self.voice_for(plan) in self._clones else "stock"

    def create_clone(self, name: str, reference: Path) -> str:
        """An instant voice clone from `reference` (a WAV of the speaker). One
        call, no characters billed; a plan with no free voice slot or a key
        without the voices_write permission says so in a plain sentence."""
        status, voice_id, text = self._add_voice(self._api_key, name, Path(reference).read_bytes(), self._timeout)
        if status != 200:
            _raise_for(status, text.replace(self._api_key, "***"))
        self._clones.add(voice_id)
        return voice_id

    def revoice(self, source: Source, plan: EditPlan, audio: MediaArtifact) -> MediaArtifact | None:
        """The Voice Changer (15b): pass a finished take through the speaker's
        clone, so it keeps its timing and delivery but takes the clone's timbre.
        None when this take is not in a clone (nothing to convert to). Charged
        by the second before the call and refunded if nothing came back."""
        voice_id = self.voice_for(plan)
        if voice_id not in self._clones:
            return None
        cost = math.ceil(audio.duration * STS_CHARS_PER_SECOND)
        self._budget.charge(source.project_id, cost)
        try:
            status, content, text = self._convert(
                self._api_key, voice_id, Path(audio.path).read_bytes(), self._timeout,
            )
        except VoiceError:
            self._budget.refund(source.project_id, cost)
            raise
        if status != 200:
            self._budget.refund(source.project_id, cost)
            _raise_for(status, text.replace(self._api_key, "***"))
        with tempfile.TemporaryDirectory() as tmp:
            raw, _ = ffmpeg.pcm_to_wav(content, Path(tmp) / "changed.wav", SAMPLE_RATE)
            # The same length as the take it came from, so it drops into the same slot.
            exact = Path(tmp) / "exact.wav"
            ffmpeg._run(ffmpeg.FFMPEG, [
                "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN, "-i", str(raw),
                "-af", "apad", "-t", f"{audio.duration:.3f}", "-c:a", "pcm_s16le", *ffmpeg._BITEXACT_OUT, str(exact),
            ])
            return self._store.put_file(
                source.project_id, exact, kind="audio", container="wav", duration=ffmpeg.duration_of(exact),
            )

    def delete_clone(self, voice_id: str) -> None:
        """Remove a clone from the vendor. Already gone (404) counts as done."""
        status, text = self._delete_voice(self._api_key, voice_id, self._timeout)
        if status not in (200, 404):
            _raise_for(status, text.replace(self._api_key, "***"))
        self._clones.discard(voice_id)

    def _take(self, project_id: str, voice_id: str, body: dict, plan: EditPlan) -> tuple[bytes, tuple[Word, ...]]:
        # Charged per attempt, before the call, so concurrent jobs can never
        # squeeze under the ceiling together; a call that fails before anything
        # is made gives the charge back (the chaos pass: a 429 storm used to eat the cap).
        cost = self.cost_of(plan)
        self._budget.charge(project_id, cost)
        try:
            status, content, text = self._post(voice_id, body, self._api_key, self._timeout)
        except VoiceError:
            self._budget.refund(project_id, cost)
            raise
        if status != 200:
            self._budget.refund(project_id, cost)
            _raise_for(status, text.replace(self._api_key, "***"))
        return decode_response(content)

    def _choose(self, project_id: str, voice_id: str, body: dict, plan: EditPlan,
                target: float, notes: list[str]) -> tuple[bytes, tuple[Word, ...]]:
        """Takes by duration (Phase 14): the first take is kept when it is
        within tolerance of the slot; otherwise more takes are voiced and the
        nearest kept, and when even that is too far for a tempo change the
        model's own speed control is tried once."""
        takes = [self._take(project_id, voice_id, body, plan)]
        ratio = lambda take: (len(take[0]) / 2 / SAMPLE_RATE) / target   # noqa: E731
        if abs(ratio(takes[0]) - 1) <= self._tolerance:
            return takes[0]
        for _ in range(self._takes - 1):
            takes.append(self._take(project_id, voice_id, body, plan))
        best = min(takes, key=lambda take: abs(ratio(take) - 1))
        if len(takes) > 1:
            notes.append(f"nearest of {len(takes)} takes")
        r = ratio(best)
        # Too far for a tempo change, but within the model's speed range once
        # the two are combined: generate again at that speed.
        if (r > ffmpeg.MAX_TEMPO and r <= ffmpeg.MAX_TEMPO * SPEED_MAX) or \
           (r < ffmpeg.MIN_TEMPO and r >= ffmpeg.MIN_TEMPO * SPEED_MIN):
            speed = min(SPEED_MAX, max(SPEED_MIN, r))
            faster = self._take(project_id, voice_id, {**body, "voice_settings": {"speed": round(speed, 2)}}, plan)
            if abs(ratio(faster) - 1) < abs(r - 1):
                notes.append(f"spoken at {speed:.2f}× by the model")
                return faster
        return best

    def synthesize(
        self, source: Source, plan: EditPlan, transcript: Transcript | None = None,
    ) -> MediaArtifact:
        body = to_request(plan, transcript, self._model)
        voice_id = self.voice_for(plan)
        key = f"{source.project_id}|{voice_id}|{json.dumps(body, sort_keys=True)}"
        target = plan.selection.end - plan.selection.start
        notes: list[str] = []
        held = self._held.pop(key, None)
        if held is None:
            if plan.fit is None and plan.mix != "concatenate":
                held = self._choose(source.project_id, voice_id, body, plan, target, notes)
            else:
                held = self._take(source.project_id, voice_id, body, plan)
        audio, words = held

        with tempfile.TemporaryDirectory() as tmp:
            raw, _ = ffmpeg.pcm_to_wav(audio, Path(tmp) / "raw.wav", SAMPLE_RATE)
            try:
                placed, duration, fitted, words = fit.place(
                    raw, Path(tmp) / "voice.wav", target, plan.fit, plan.mix, self._tolerance, words, flex_max=self._flex_max,
                )
            except ffmpeg.SpanMismatch:
                self._held[key] = held
                raise
            self.last_notes = notes + fitted
            self.last_words = words
            return self._store.put_file(
                source.project_id, placed, kind="audio", container="wav", duration=duration,
            )
