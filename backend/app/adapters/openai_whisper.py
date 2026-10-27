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

from app.adapters.base import idempotency_header, VendorError
from app.domain.models import Source, Statement, Transcript, Word
from app.domain.transcript import assign_speakers
from app.media import ffmpeg, vad

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
    # Bug 3 (2026-10-19): the same sign-offs in the languages Whisper invents them in.
    # Chinese (traditional and simplified)
    "謝謝觀看", "谢谢观看", "多謝您的觀看", "多谢您的观看", "謝謝您的觀看", "谢谢您的观看", "感謝觀看", "感谢观看",
    "謝謝收看", "谢谢收看", "感謝收看", "感谢收看", "請訂閱", "请订阅", "請不吝點贊訂閱轉發打賞支持明鏡與點點欄目",
    "字幕由amara org社區提供", "字幕由amara org社区提供",
    # Japanese
    "ご視聴ありがとうございました", "ご視聴ありがとうございます", "ありがとうございました", "チャンネル登録お願いします",
    "チャンネル登録よろしくお願いします", "おやすみなさい",
    # Korean
    "시청해주셔서 감사합니다", "시청해 주셔서 감사합니다", "구독과 좋아요 부탁드립니다", "구독 부탁드립니다", "감사합니다",
    # Hindi
    "देखने के लिए धन्यवाद", "धन्यवाद", "सब्सक्राइब करें", "चैनल को सब्सक्राइब करें", "वीडियो देखने के लिए धन्यवाद",
    # Run 5 item 4: the subtitle credits and channel lines Whisper copies from
    # its training captions, in the Latin-script languages the script check
    # cannot tell apart from English.
    "subtítulos realizados por la comunidad de amara org", "subtitulos realizados por la comunidad de amara org",
    "subtítulos por la comunidad de amara org", "sous titres réalisés para la communauté d amara org",
    "sous titres réalisés par la communauté d amara org", "untertitel der amara org community",
    "untertitel im auftrag des zdf für funk 2017", "untertitel im auftrag des zdf 2017", "untertitel von stephanie geiges",
    "legendas pela comunidade amara org", "sottotitoli creati dalla comunità amara org",
    "ondertiteling door de amara org gemeenschap", "napisy stworzone przez społeczność amara org",
    "продолжение следует", "субтитры сделал dimatorzok", "субтитры создавались сообществом amara org",
    "редактор субтитров а семкин корректор а егорова",
    "thank you very much for watching", "thanks for watching and see you next time", "don t forget to subscribe",
    "please like and subscribe", "hit the bell", "bye bye",
}
# Run 5 item 4: what a caption writes for sound that is not speech. In
# brackets ("[Music]") or as bare symbols ("♪ ♪") it always goes; as bare
# words it is held to the known phrases' doubt bar.
SOUND_CAPTIONS = {
    "music", "music playing", "upbeat music", "soft music", "dramatic music", "gentle music", "background music",
    "instrumental music", "music continues", "music fades", "applause", "laughter", "laughs", "silence", "no audio",
    "inaudible", "noise", "static", "wind", "birds chirping", "sighs", "breathing", "coughs",
    "音楽", "音乐", "拍手", "笑", "música", "musica", "musique", "musik", "음악", "박수", "संगीत", "музыка",
}
_BRACKETED = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】|[♪♫][^♪♫]*[♪♫]|\*[^*]*\*)\s*$")
# "Thanks for watching" and "subscribe" in any language: a short segment that
# holds one of these is a sign-off too, however it is worded around them.
SIGN_OFF_STEMS = (
    "watching", "subscribe", "gracias por ver", "suscríbete", "suscribete", "merci davoir regardé", "abonnez",
    "danke fürs zuschauen", "abonniert", "obrigado por assistir", "inscrevase", "grazie per la visione", "iscriviti",
    "спасибо за просмотр", "подписывайтесь", "観看", "观看", "收看", "訂閱", "订阅", "視聴", "チャンネル登録",
    "시청", "구독", "देखने के लिए धन्यवाद", "सब्सक्राइब",
)
SIGN_OFF_MAX_WORDS = 8

# A segment in another script than the clip's own language is held to a
# stricter doubt bar than ordinary speech (real code-switching — Hinglish —
# speaks with confidence; an invented sign-off does not).
OFF_LANGUAGE_NO_SPEECH = 0.3
OFF_LANGUAGE_LOGPROB = -0.7
SCRIPT_OF_LANGUAGE = {
    "chinese": "han", "japanese": "kana", "korean": "hangul", "hindi": "devanagari", "marathi": "devanagari",
    "nepali": "devanagari", "russian": "cyrillic", "ukrainian": "cyrillic", "arabic": "arabic", "urdu": "arabic",
    "persian": "arabic", "hebrew": "hebrew", "greek": "greek", "thai": "thai", "tamil": "tamil", "telugu": "telugu",
    "bengali": "bengali", "gujarati": "gujarati", "kannada": "kannada", "malayalam": "malayalam", "punjabi": "gurmukhi",
}
# Speech has to stand out from the recording's own noise by this much.
SPEECH_ABOVE_FLOOR_DB = 8.0
# Run 5 item 8 (evals/messy): under a loud music bed the quietest tenth of the
# clip IS the music, so real speech 6 dB over it read as 7 to 8 dB "over the
# floor" and four of five lines were dropped. A statement that misses the floor
# bar gets a second chance against what plays between the words: speech adds
# to the bed there, an invented line over music does not.
SPEECH_ABOVE_GAPS_DB = 4.0
MIN_GAP_SECONDS = 1.0           # this much sound between words to judge by
GAP_PAD = 0.05                  # seconds kept clear around each word
# A word this close to a dropped segment's edge belongs to it (seconds).
EDGE = 0.02

_PUNCT = re.compile(r"[^\w\s]")


def _normal(text: str) -> str:
    """Lower case, punctuation and symbols gone, spaces single. Only
    punctuation and symbols go: Devanagari's vowel signs are marks, not
    letters, and must stay (bug 3: Hindi sign-offs never matched)."""
    import unicodedata
    kept = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text.lower())
    return re.sub(r"\s+", " ", kept).strip()


def script_of(text: str) -> str | None:
    """The writing system most of a text's letters are in, or None when it has none."""
    counts: dict[str, int] = {}
    for ch in text:
        o = ord(ch)
        name = ("han" if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF else
                "kana" if 0x3040 <= o <= 0x30FF else
                "hangul" if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF else
                "devanagari" if 0x0900 <= o <= 0x097F else
                "cyrillic" if 0x0400 <= o <= 0x04FF else
                "arabic" if 0x0600 <= o <= 0x06FF else
                "hebrew" if 0x0590 <= o <= 0x05FF else
                "greek" if 0x0370 <= o <= 0x03FF else
                "thai" if 0x0E00 <= o <= 0x0E7F else
                "latin" if ch.isalpha() and o < 0x0250 else None)
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    # Japanese mixes kana and kanji: any kana makes it Japanese.
    if counts.get("kana"):
        return "kana"
    return max(counts, key=counts.get)


def clip_script(payload: dict) -> str | None:
    """The clip's own writing system: from the confident segments' text when
    there are any (Whisper's one `language` guess is unreliable on a mostly
    silent clip), else from that guess."""
    weights: dict[str, float] = {}
    for seg in payload.get("segments") or []:
        nsp = seg.get("no_speech_prob")
        lp = seg.get("avg_logprob")
        if (nsp is not None and float(nsp) > 0.2) or (lp is not None and float(lp) < -0.5):
            continue
        sc = script_of(seg.get("text") or "")
        if sc:
            try:
                weights[sc] = weights.get(sc, 0.0) + max(0.0, float(seg["end"]) - float(seg["start"]))
            except (KeyError, TypeError, ValueError):
                continue
    if weights:
        return max(weights, key=weights.get)
    lang = (payload.get("language") or "").lower()
    return SCRIPT_OF_LANGUAGE.get(lang, "latin" if lang else None)


def is_sign_off(text: str) -> bool:
    n = _normal(text)
    if n in HALLUCINATIONS or n in SOUND_CAPTIONS:
        return True
    words = n.split()
    return 0 < len(words) <= SIGN_OFF_MAX_WORDS and any(stem.replace(" ", "") in n.replace(" ", "") for stem in SIGN_OFF_STEMS)


def is_sound_caption(text: str) -> bool:
    """Run 5 item 4: "[Music]", "♪", "(upbeat music)", "[音楽]", "♪ la la ♪":
    a caption for a sound, not speech. A segment wholly in brackets or
    between music notes, or with no letters or digits at all."""
    stripped = text.strip()
    return bool(stripped) and (not _normal(stripped) or bool(_BRACKETED.match(stripped)))


# Run 5 item 4: a segment in another writing system than the clip's is kept
# only when it is long enough to be real speech as well as confident.
OFF_LANGUAGE_MIN_SECONDS = 1.0


def doubtful(segment: dict, clip: str | None = None) -> str | None:
    """Why a segment looks invented, or None when it looks like real speech.
    `clip` is the clip's own writing system (see `clip_script`)."""
    if is_sound_caption(segment.get("text") or ""):
        return "a caption for a sound, not speech"
    nsp = segment.get("no_speech_prob")
    if nsp is not None and float(nsp) > NO_SPEECH_PROB_MAX:
        return f"no_speech_prob {float(nsp):.2f}"
    lp = segment.get("avg_logprob")
    if lp is not None and float(lp) < AVG_LOGPROB_MIN:
        return f"avg_logprob {float(lp):.2f}"
    cr = segment.get("compression_ratio")
    if cr is not None and float(cr) > COMPRESSION_RATIO_MAX:
        return f"compression_ratio {float(cr):.2f}"
    if is_sign_off(segment.get("text") or "") and (nsp is None or float(nsp) > KNOWN_PHRASE_NO_SPEECH):
        return "a phrase Whisper invents on silence"
    script = script_of(segment.get("text") or "")
    if clip and script and script != clip and (
            (nsp is not None and float(nsp) > OFF_LANGUAGE_NO_SPEECH) or (lp is not None and float(lp) < OFF_LANGUAGE_LOGPROB)):
        return f"{script} on a {clip} clip, and Whisper unsure of it"
    if clip and script and script != clip:
        try:
            seconds = float(segment["end"]) - float(segment["start"])
        except (KeyError, TypeError, ValueError):
            seconds = 0.0
        if seconds < OFF_LANGUAGE_MIN_SECONDS:
            return f"{script} on a {clip} clip, too short to be real speech"
    return None


def to_transcript(payload: dict) -> Transcript:
    """Turn a verbose_json response into the domain Transcript, leaving out
    the segments (and their words) that Whisper most likely made up."""
    dropped: list[tuple[float, float]] = []
    clip = clip_script(payload)
    for raw in payload.get("segments") or []:
        why = doubtful(raw, clip)
        if why:
            try:
                dropped.append((float(raw["start"]), float(raw["end"])))
            except (KeyError, TypeError, ValueError):
                continue
            log.info("dropped a doubtful segment %r: %s", (raw.get("text") or "").strip(), why)

    def invented(start: float, end: float) -> bool:
        # Bug 3: a word inside a dropped segment goes with it, even a zero-length
        # one sitting on its edge — Whisper's "謝您的觀看" were five words at 6.90–6.90 on a segment ending at 6.90.
        return any(start < b and a < end or (a - EDGE <= start <= b + EDGE and a - EDGE <= end <= b + EDGE) for a, b in dropped)

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
    if statements and all(is_sign_off(st.text) for st in statements):
        # Run 5 item 4: a clip that says nothing but "Thank you." or "Thanks
        # for watching" is the classic invention on silence or music, however
        # sure Whisper is of it.
        log.info("dropped a lone sign-off %r", " ".join(st.text for st in statements))
        return Transcript(words=())
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
    between = _between_words_db(audio, transcript)
    kept, dropped = [], []
    for st in transcript.statements:
        span = audio[int(st.start * signals.RATE): int(st.end * signals.RATE)]
        level = signals.speech_level_db(span) if len(span) else None
        over_bed = level is not None and between is not None and level - between >= SPEECH_ABOVE_GAPS_DB
        if level is None or (level - floor < SPEECH_ABOVE_FLOOR_DB and not over_bed):
            dropped.append(st)
            log.info("dropped %r: no speech energy there (%s dB over a %.0f dB floor)",
                     st.text, "none" if level is None else f"{level - floor:.0f}", floor)
        else:
            kept.append(st)
    if not dropped:
        return transcript
    words = tuple(w for w in transcript.words
                  if not any(w.start < d.end and d.start < w.end
                             or (d.start - EDGE <= w.start <= d.end + EDGE and d.start - EDGE <= w.end <= d.end + EDGE) for d in dropped))
    return Transcript(words=words, statements=tuple(kept))


def _between_words_db(audio, transcript: Transcript) -> float | None:
    """The level of what plays between the words (the bed, the room), as RMS
    in dB, or None with too little of it to judge by (run 5 item 8)."""
    import numpy as np

    from app.continuity import signals
    rate = signals.RATE
    keep = np.ones(len(audio), dtype=bool)
    for w in transcript.words:
        keep[max(0, int((w.start - GAP_PAD) * rate)): int((w.end + GAP_PAD) * rate)] = False
    if keep.sum() < MIN_GAP_SECONDS * rate:
        return None
    power = float(np.mean(np.asarray(audio, dtype=np.float64)[keep] ** 2))
    return 10 * np.log10(max(power, 1e-10))


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(audio_path: Path, api_key: str, timeout: float) -> dict:
    with audio_path.open("rb") as handle:
        response = httpx.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", **idempotency_header("transcribe", _sha(audio_path))},
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
                headers={"Authorization": f"Bearer {api_key}", **idempotency_header("diarize", _sha(audio_path))},
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
        # Send only the spans where someone might be speaking (run 5 item 4),
        # and drop statements with no speech energy behind them. Off only in
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
        Diarization failing never fails the upload: the words stand alone.

        Run 5 item 4: both calls hear only the spans where someone might be
        speaking (`media/vad.py`), and every time in their replies is mapped
        back onto the clip. A clip with no such span is not sent at all."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            sent, mapping = self._speech_only(audio, Path(tmp))
            if sent is None:
                log.info("no speech heard in %s; nothing sent to be transcribed", source.project_id)
                return Transcript(words=())
            transcript = to_transcript(vad.map_times(self._post(sent, self._api_key, self._timeout), mapping))
            if self._screen_silence:
                transcript = without_silent_speech(transcript, audio)
            if not transcript.words:
                return transcript
            try:
                turns = to_turns(vad.map_times(self._post_diarize(sent, self._api_key, self._timeout), mapping))
            except TranscriptionError as exc:
                log.warning("diarization failed for %s: %s", source.project_id, exc)
                return transcript
        return assign_speakers(transcript, turns)

    def _speech_only(self, audio: Path, tmp: Path) -> tuple[Path | None, vad.TimeMap | None]:
        """What to send for `audio` (None when nothing is speech), and the map
        from its times back to the clip's (None when it is the clip itself)."""
        if not self._screen_silence:
            return audio, None
        try:
            sent, mapping, spans = vad.speech_only(audio, tmp / "speech.wav")
        except Exception:  # noqa: BLE001 - a failed measurement sends the whole clip, as before
            log.exception("voice activity detection failed; sending the whole clip")
            return audio, None
        return (sent, mapping) if spans else (None, None)

    def hear(self, source: Source) -> list[str]:
        """9a: the words alone, in order, for checking a take against the
        project's glossary. One call, no diarization, no silence screen (a
        take is all speech)."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            transcript = to_transcript(self._post(audio, self._api_key, self._timeout))
        return [w.text for w in transcript.words]

    def diarize(self, source: Source) -> list[Turn]:
        """Speaker turns alone — for projects transcribed before Phase 11."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = self._audio(source, Path(tmp))
            sent, mapping = self._speech_only(audio, Path(tmp))
            if sent is None:
                return []
            return to_turns(vad.map_times(self._post_diarize(sent, self._api_key, self._timeout), mapping))

    def _audio(self, source: Source, tmp: Path) -> Path:
        audio = tmp / "audio.wav"
        try:
            ffmpeg.extract_audio(source.media.path, audio)
        except ffmpeg.FFmpegError as exc:
            raise TranscriptionError("Could not extract audio from the source video.") from exc
        return audio
