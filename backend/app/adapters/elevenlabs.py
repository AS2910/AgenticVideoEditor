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

Phase 20b (spiked 2026-10-17): eleven_v3 and eleven_v4 speak *audio tags*
written in the text ("[sighs]", "[whispers]"); the tag's characters are billed
and get a span in the alignment, which `words_from_alignment` drops. v3 still
refuses the context; v4 accepts it. multilingual_v2 reads a tag as words, so
tags are stripped before it. A voice can be designed from words
(`/v1/text-to-voice/design`, eleven_ttv_v3): three previews of ~25 s for about
350 credits, a sample text of 100+ characters or the vendor's own; saving a
preview takes a voice slot and no credits.
"""
from __future__ import annotations

import hashlib

import base64
import json
import math
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator

import httpx

from app.adapters.base import idempotency_header, VendorError
from app.adapters.pronounce import for_synthesis
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
# The voice library (shared voices): searched by accent, added to the account
# by its owner's id and the voice's id, under a name of our choosing.
LIBRARY_ENDPOINT = "https://api.elevenlabs.io/v1/shared-voices"
ADD_LIBRARY_ENDPOINT = "https://api.elevenlabs.io/v1/voices/add/{owner_id}/{voice_id}"
VOICE_ENDPOINT = "https://api.elevenlabs.io/v1/voices/{voice_id}"
# P-3: the same call, answered as JSON with the audio in base64 and a time for
# every character, from which the take's own word times are read.
TIMESTAMPS_ENDPOINT = ENDPOINT + "/with-timestamps"
VOICES_ENDPOINT = "https://api.elevenlabs.io/v2/voices"
# 20b: a voice from words. Previews first (billed by the sample text), then
# one of them is kept as a voice of the account (a slot, no credits).
DESIGN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-voice/design"
CREATE_VOICE_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-voice"
SUBSCRIPTION_ENDPOINT = "https://api.elevenlabs.io/v1/user/subscription"
DESIGN_MODEL = "eleven_ttv_v3"
DESIGN_CHARS = 350          # what a design with the vendor's own sample text billed, measured
DESIGN_TEXT_MIN = 100       # the API's floor for a sample text of our own
# Which models take what (measured 2026-10-17). Short names are what Voltage
# says; the vendor ids are what is sent.
MODELS = {"v2": "eleven_multilingual_v2", "v3": "eleven_v3", "v4": "eleven_v4"}
TAG_MODELS = frozenset({"eleven_v3", "eleven_v3_conversational", "eleven_v4", "eleven_v4_turbo"})
NO_CONTEXT_MODELS = frozenset({"eleven_v3", "eleven_v3_conversational"})
_TAG = re.compile(r"\[[^\[\]\n]{1,40}\]")
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
    "eleven_v4_turbo": 0.5,
}

# (status, body bytes, body text)
PostFn = Callable[[str, dict, str, float], tuple[int, bytes, str]]
# (api key, name, wav bytes, timeout) -> (status, new voice id, body text)
AddVoiceFn = Callable[[str, str, bytes, float], tuple[int, str, str]]
# (api key, voice id, wav bytes, timeout) -> (status, pcm bytes, body text)
ConvertFn = Callable[[str, str, bytes, float], tuple[int, bytes, str]]
# (api key, voice id, timeout) -> (status, body text)
DeleteVoiceFn = Callable[[str, str, float], tuple[int, str]]
# (api key, description, sample text or None, timeout) -> (status, payload, error text)
DesignFn = Callable[[str, str, str | None, float], tuple[int, dict, str]]
# (api key, name, description, generated voice id, timeout) -> (status, voice id, error text)
CreateVoiceFn = Callable[[str, str, str, str, float], tuple[int, str, str]]


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
        # "premade" (ElevenLabs' own), "professional"/"high_quality" (from the
        # library), "cloned" (a speaker's own, made by Voltage; never listed).
        "category": raw.get("category"),
        # The vendor's own sample of the voice, so the voices page can play it.
        "preview_url": raw.get("preview_url") or None,
    }


def in_catalogue(raw: dict) -> bool:
    """Which of the account's voices a user may pick: ElevenLabs' own and the
    ones added from the library — never a clone Voltage made of a speaker."""
    return raw.get("category") != "cloned" and not str(raw.get("name", "")).startswith("voltage-")


def _get_voices(api_key: str, timeout: float) -> list[dict]:
    """Every voice the account can speak in that a user may pick: the premade
    ones and those added from the library (15e), clones left out."""
    try:
        response = httpx.get(
            VOICES_ENDPOINT, params={"page_size": 100},
            headers={"xi-api-key": api_key}, timeout=timeout,
        )
    except httpx.HTTPError:
        raise VoiceError("Could not reach ElevenLabs to list voices.") from None
    if response.status_code != 200:
        _raise_for(response.status_code, response.text.replace(api_key, "***"))
    voices = [to_voice(v) for v in response.json().get("voices", []) if in_catalogue(v)]
    # ElevenLabs' own first, then the library's, each in the order they came.
    return sorted(voices, key=lambda v: 0 if v.get("category") == "premade" else 1)


def _search_library(api_key: str, accent: str, timeout: float, *, language: str = "en",
                    page_size: int = 30, use_case: str | None = None) -> list[dict]:
    """Voices in the library with this accent, most-used first. Each comes
    with `public_owner_id`, needed to add it."""
    params: dict = {"accent": accent, "language": language, "page_size": page_size, "sort": "cloned_by_count"}
    if use_case:
        params["use_cases"] = use_case
    try:
        response = httpx.get(
            LIBRARY_ENDPOINT, params=params,
            headers={"xi-api-key": api_key}, timeout=timeout,
        )
    except httpx.HTTPError:
        raise VoiceError("Could not reach ElevenLabs to search the voice library.") from None
    if response.status_code != 200:
        _raise_for(response.status_code, response.text.replace(api_key, "***"))
    out = []
    for v in response.json().get("voices", []):
        out.append({
            "voice_id": v["voice_id"], "public_owner_id": v["public_owner_id"], "name": v["name"],
            "gender": v.get("gender"), "accent": v.get("accent"), "age": v.get("age"),
            "description": (v.get("description") or "").strip(), "category": v.get("category"),
            "use_case": v.get("use_case"), "uses": int(v.get("cloned_by_count") or 0),
            "free": bool(v.get("free_users_allowed", True)),
        })
    return out


def _add_from_library(api_key: str, owner_id: str, voice_id: str, name: str, timeout: float) -> tuple[int, str, str]:
    """Add a library voice to the account under `name`. Answers (status,
    voice_id, error text); the voice keeps its id."""
    try:
        response = httpx.post(
            ADD_LIBRARY_ENDPOINT.format(owner_id=owner_id, voice_id=voice_id),
            headers={"xi-api-key": api_key, **idempotency_header("library", voice_id, name)}, json={"new_name": name}, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    if response.status_code != 200:
        return response.status_code, "", response.text
    try:
        return 200, str(response.json().get("voice_id") or voice_id), ""
    except ValueError:
        return 200, voice_id, ""


def billed_characters(text: str, model: str) -> int:
    return math.ceil(len(text) * _COST_MULTIPLIER.get(model, 1.0))


def model_of(plan: EditPlan, default: str) -> str:
    """The vendor model this take is spoken with: the plan's (a short name
    or a vendor id), else the adapter's default."""
    wanted = (plan.model or "").strip()
    return MODELS.get(wanted, wanted) if wanted else default


def spoken_text(text: str, model: str) -> str:
    """The text as sent: audio tags stay for a model that performs them and
    go for one that would read them aloud."""
    if model in TAG_MODELS:
        return text
    return re.sub(r"  +", " ", _TAG.sub("", text)).strip()


def has_tags(text: str) -> bool:
    return bool(_TAG.search(text))


_SETTING_RANGE = {"stability": (0.0, 1.0), "similarity_boost": (0.0, 1.0), "style": (0.0, 1.0), "speed": (SPEED_MIN, SPEED_MAX)}


def clamp_settings(settings: dict | None) -> dict:
    """The vendor's voice settings Voltage may set, each within the API's
    range; anything else is dropped."""
    out: dict = {}
    for key, value in (settings or {}).items():
        if value is None:
            continue
        if key == "use_speaker_boost":
            out[key] = bool(value)
        elif key in _SETTING_RANGE:
            lo, hi = _SETTING_RANGE[key]
            out[key] = round(min(hi, max(lo, float(value))), 2)
    return out


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


# 9b: whether the words around a line go to the vendor as previous/next
# context. Off around a language version's takes (unless AVE_LANG_MASTER_CONTEXT
# is on): its transcript is the master's English, which can anglicise a
# translated line. Set by the caller around the generation, like the respellings.
_SEND_CONTEXT: ContextVar[bool] = ContextVar("vendor_context", default=True)


@contextmanager
def vendor_context(on: bool) -> Iterator[None]:
    token = _SEND_CONTEXT.set(bool(on))
    try:
        yield
    finally:
        _SEND_CONTEXT.reset(token)


def sends_context() -> bool:
    return _SEND_CONTEXT.get()


def to_request(plan: EditPlan, transcript: Transcript | None, model: str, speed: float = 1.0) -> dict:
    model = model_of(plan, model)
    # A3: the project's respellings go in the text sent; the plan keeps the words as written.
    body: dict = {"text": spoken_text(for_synthesis(plan.new_text), model), "model_id": model}
    settings: dict = (clamp_settings(plan.voice_settings) if plan.voice_settings
                      else dict(DELIVERY_SETTINGS.get((plan.delivery or "").lower(), {})))
    if abs(speed - 1.0) > 1e-3:
        settings["speed"] = round(min(SPEED_MAX, max(SPEED_MIN, speed * settings.get("speed", 1.0))), 2)
    if settings:
        body["voice_settings"] = settings
    if transcript is None or model in NO_CONTEXT_MODELS or not _SEND_CONTEXT.get():
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
            headers={"xi-api-key": api_key, **idempotency_header("tts", voice_id, json.dumps(body, sort_keys=True))},
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
    return _without_tags(words)


def _without_tags(words: list[Word]) -> tuple[Word, ...]:
    """An audio tag ("[sighs]", "[long pause]") is performed, not said: its
    span stays in the audio and leaves the word list."""
    out: list[Word] = []
    inside = False
    for w in words:
        if not inside and w.text.startswith("["):
            inside = not w.text.endswith("]")
            continue
        if inside:
            inside = not w.text.endswith("]")
            continue
        out.append(w)
    return tuple(out)


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
            headers={"xi-api-key": api_key, **idempotency_header("clone", name, hashlib.sha256(wav).hexdigest())},
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
            headers={"xi-api-key": api_key, **idempotency_header("sts", voice_id, hashlib.sha256(wav).hexdigest())},
            data={"model_id": STS_MODEL, "remove_background_noise": "true"},
            files={"audio": ("take.wav", wav, "audio/wav")},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    ok = response.status_code == 200
    return response.status_code, response.content if ok else b"", "" if ok else response.text


def _design(api_key: str, description: str, text: str | None, timeout: float) -> tuple[int, dict, str]:
    body: dict = {"voice_description": description, "model_id": DESIGN_MODEL}
    if text:
        body["text"] = text
    else:
        body["auto_generate_text"] = True
    try:
        response = httpx.post(DESIGN_ENDPOINT, headers={"xi-api-key": api_key, **idempotency_header("design", json.dumps(body, sort_keys=True))},
                              json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    if response.status_code != 200:
        return response.status_code, {}, response.text
    try:
        return 200, response.json(), ""
    except ValueError:
        return 502, {}, "ElevenLabs answered without previews."


def _create_voice(api_key: str, name: str, description: str, generated_voice_id: str, timeout: float) -> tuple[int, str, str]:
    try:
        response = httpx.post(
            CREATE_VOICE_ENDPOINT, headers={"xi-api-key": api_key, **idempotency_header("save", generated_voice_id, name)}, timeout=timeout,
            json={"voice_name": name, "voice_description": description, "generated_voice_id": generated_voice_id},
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach ElevenLabs ({type(exc).__name__}).") from None
    if response.status_code != 200:
        return response.status_code, "", response.text
    try:
        return 200, str(response.json()["voice_id"]), ""
    except (ValueError, KeyError):
        return 502, "", "ElevenLabs answered without a voice id."


def _subscription(api_key: str, timeout: float) -> dict:
    """The account's slots and credits; {} when it cannot be read (the
    endpoint is rate-limited), so a caller says "unknown", never a number."""
    try:
        response = httpx.get(SUBSCRIPTION_ENDPOINT, headers={"xi-api-key": api_key}, timeout=timeout)
    except httpx.HTTPError:
        return {}
    if response.status_code != 200:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


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
        search_library: Callable[..., list[dict]] = _search_library,
        add_from_library: Callable[..., tuple[int, str, str]] = _add_from_library,
        design: DesignFn = _design,
        create_voice: CreateVoiceFn = _create_voice,
        subscription: Callable[[str, float], dict] = _subscription,
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
        self._search_library = search_library
        self._add_from_library = add_from_library
        self._design = design
        self._create_voice = create_voice
        self._subscription = subscription
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
        # p61: the last paid take's spoken length before fitting, {seconds, speed, faster_tried}.
        self.last_measure: dict | None = None
        self._faster_tried: float | None = None
        self._chosen_speed: float | None = None

    def cost_of(self, plan: EditPlan) -> int:
        model = model_of(plan, self._model)
        return billed_characters(spoken_text(plan.new_text, model), model)

    @property
    def model(self) -> str:
        return self._model

    @property
    def default_voice(self) -> str:
        return self._voice_id

    @property
    def takes_per_line(self) -> int:
        """How many takes one line costs (Phase 14: takes by duration)."""
        return self._takes

    def voices(self) -> list[dict]:
        """The voices a user may pick — ElevenLabs' own and those added from
        the library — fetched once. Listing is free."""
        if self._voices is None:
            self._voices = self._get_voices(self._api_key, self._timeout)
        return self._voices

    # ── the voice library (15e) ──

    def library(self, accent: str, *, language: str = "en") -> list[dict]:
        """Library voices with this accent, most-used first. Free to search."""
        return self._search_library(self._api_key, accent, self._timeout, language=language)

    def add_from_library(self, owner_id: str, voice_id: str, name: str) -> str:
        """Add a library voice to the account (it takes a voice slot; no
        characters billed) and put it in the catalogue."""
        status, added, text = self._add_from_library(self._api_key, owner_id, voice_id, name, self._timeout)
        if status != 200:
            _raise_for(status, text.replace(self._api_key, "***"))
        self._voices = None
        return added

    # ── a voice from words (20b) ──

    def design_cost(self) -> int:
        """What one design is likely to bill, in characters."""
        return DESIGN_CHARS

    def design_voice(self, project_id: str, description: str, text: str | None = None) -> list[dict]:
        """Up to three previews of a voice described in words, each
        {generated_voice_id, audio (mp3 bytes), media_type, duration, text}.
        Billed by the sample text's characters: charged as an estimate before
        the call and trued up to the text the vendor used."""
        if text is not None and len(text) < DESIGN_TEXT_MIN:
            raise VoiceConfigError(f"A sample text needs at least {DESIGN_TEXT_MIN} characters; "
                                   "leave it out and the vendor writes one.")
        estimate = len(text) if text else DESIGN_CHARS
        with self._budget.held(project_id, estimate):
            status, payload, err = self._design(self._api_key, description, text, self._timeout)
            if status != 200:
                _raise_for(status, err.replace(self._api_key, "***"))
        used = payload.get("text") or text or ""
        actual = len(used) or estimate
        if actual < estimate:
            self._budget.refund(project_id, estimate - actual)
        elif actual > estimate:
            try:
                self._budget.charge(project_id, actual - estimate)
            except Exception:  # noqa: BLE001 — the money is spent either way; the ceiling catches the next step
                pass
        previews = []
        for pv in payload.get("previews", []):
            previews.append({
                "generated_voice_id": pv["generated_voice_id"],
                "audio": base64.b64decode(pv.get("audio_base_64") or ""),
                "media_type": pv.get("media_type") or "audio/mpeg",
                "duration": float(pv.get("duration_secs") or 0.0),
                "text": used,
            })
        return previews

    def save_voice(self, generated_voice_id: str, name: str, description: str) -> str:
        """Keep a preview as a voice of the account (a slot, no credits) and
        put it in the catalogue."""
        status, voice_id, err = self._create_voice(self._api_key, name, description, generated_voice_id, self._timeout)
        if status != 200:
            _raise_for(status, err.replace(self._api_key, "***"))
        self._voices = None
        return voice_id

    def delete_voice(self, voice_id: str) -> None:
        """Remove a voice from the account (one Voltage made: a clone, a
        designed voice, a library add). Already gone (404) counts as done."""
        status, text = self._delete_voice(self._api_key, voice_id, self._timeout)
        if status not in (200, 404):
            _raise_for(status, text.replace(self._api_key, "***"))
        self._clones.discard(voice_id)
        self._voices = None

    def slots(self) -> tuple[int, int] | None:
        """(used, limit) voice slots on the account, or None when unknown."""
        sub = self._subscription(self._api_key, self._timeout)
        if not sub or "voice_limit" not in sub:
            return None
        return int(sub.get("voice_slots_used") or 0), int(sub["voice_limit"])

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
        with self._budget.held(source.project_id, cost):
            status, content, text = self._convert(
                self._api_key, voice_id, Path(audio.path).read_bytes(), self._timeout,
            )
            if status != 200:
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
        self.delete_voice(voice_id)

    def _take(self, project_id: str, voice_id: str, body: dict, plan: EditPlan) -> tuple[bytes, tuple[Word, ...]]:
        # Charged per attempt, before the call, so concurrent jobs can never
        # squeeze under the ceiling together; a call that fails before anything
        # is made gives the charge back (the chaos pass: a 429 storm used to eat the cap).
        cost = self.cost_of(plan)
        with self._budget.held(project_id, cost):          # refunded on any failure, and after a crash (budget.py)
            status, content, text = self._post(voice_id, body, self._api_key, self._timeout)
            if status != 200:
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
        # p61: faster only up to fit.MODEL_SPEED_MAX, past which a take stops sounding natural.
        if (r > ffmpeg.MAX_TEMPO and r <= ffmpeg.MAX_TEMPO * fit.MODEL_SPEED_MAX) or \
           (r < ffmpeg.MIN_TEMPO and r >= ffmpeg.MIN_TEMPO * SPEED_MIN):
            speed = min(fit.MODEL_SPEED_MAX, max(SPEED_MIN, r))
            faster = self._take(project_id, voice_id, {**body, "voice_settings": {**body.get("voice_settings", {}), "speed": round(speed, 2)}}, plan)
            if r > 1:
                self._faster_tried = round(speed, 2)
            if abs(ratio(faster) - 1) < abs(r - 1):
                notes.append(f"spoken at {speed:.2f}× by the model")
                self._chosen_speed = round(speed, 2)
                return faster
        return best

    def holds(self, source: Source, plan: EditPlan, transcript: Transcript | None = None) -> bool:
        """Whether a paid take for this exact line is held (it did not fit), so
        voicing it again costs nothing (p61: the fit ladder's free rungs)."""
        body = to_request(plan, transcript, self._model)
        return f"{source.project_id}|{self.voice_for(plan)}|{json.dumps(body, sort_keys=True)}" in self._held

    def synthesize(
        self, source: Source, plan: EditPlan, transcript: Transcript | None = None,
    ) -> MediaArtifact:
        body = to_request(plan, transcript, self._model)
        voice_id = self.voice_for(plan)
        key = f"{source.project_id}|{voice_id}|{json.dumps(body, sort_keys=True)}"
        target = plan.selection.end - plan.selection.start
        notes: list[str] = []
        held = self._held.pop(key, None)
        self._faster_tried, self._chosen_speed = None, None
        fresh = held is None
        if held is None:
            if plan.fit is None and plan.mix != "concatenate":
                held = self._choose(source.project_id, voice_id, body, plan, target, notes)
            else:
                held = self._take(source.project_id, voice_id, body, plan)
        audio, words = held
        # p61: the take's own spoken length before any fitting, for the voice's
        # measured rate (a held take was measured when it was paid for).
        spoken_s = (words[-1].end - words[0].start) if words else len(audio) / 2 / SAMPLE_RATE
        speed = self._chosen_speed or float((body.get("voice_settings") or {}).get("speed") or 1.0)
        self.last_measure = {"seconds": round(spoken_s, 3), "speed": speed, "faster_tried": self._faster_tried} if fresh else None

        with tempfile.TemporaryDirectory() as tmp:
            raw, _ = ffmpeg.pcm_to_wav(audio, Path(tmp) / "raw.wav", SAMPLE_RATE)
            try:
                placed, duration, fitted, words = fit.place(
                    raw, Path(tmp) / "voice.wav", target, plan.fit, plan.mix, self._tolerance, words,
                    flex_max=self._flex_max if plan.flex_max is None else max(1.0, plan.flex_max),
                )
            except ffmpeg.SpanMismatch:
                self._held[key] = held
                raise
            self.last_notes = notes + fitted
            self.last_words = words
            return self._store.put_file(
                source.project_id, placed, kind="audio", container="wav", duration=duration,
            )
