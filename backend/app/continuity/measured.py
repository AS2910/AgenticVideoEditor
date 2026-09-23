"""Measured continuity: prosody and audio integration (Phase 6a, spec §6).

Compares the generated line with the speaker's own speech either side of the
selection, corrects what can be corrected, and scores what is left.

What is measured, and why only this:
- **Prosody** is the pitch register: the median pitch of the new line against
  the surrounding speech, in semitones. Speaking rate is *not* scored — on a
  one-second span word counts are too coarse to mean anything (the original
  "20% off" would fail against its own context), and the rate is already held
  by fitting the line to the original span's length.
- **Audio integration** is the speech level (after auto-correction) and clarity
  (speech level above the clip's quietest part). A short clip has no true
  silence to read a room floor from, so clarity is what catches a noisy edit.
- Voice identity and lip-sync stay None until Phases 4b and 5.
"""
from __future__ import annotations

import math
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.continuity import signals
from app.continuity.engine import Assessment
from app.domain.models import (
    ContinuityReport, EditPlan, MediaArtifact, Selection, Source, Transcript, Word,
)
from app.media.reference import speech_runs
from app.store.artifacts import ArtifactStore

CONTEXT_WINDOW = 3.0        # seconds of speech either side that count as context
MAX_GAIN_DB = 12.0          # level correction is refused beyond this
ROOM_TONE_AUDIBLE_DB = -75  # quieter rooms are left alone: nothing to match
ROOM_BELOW_SPEECH_DB = 25   # room tone must sit this far under the speech
PEAK_CEILING = 0.99

# Score scales. Each maps a difference to 1.0 at none, falling linearly; with
# the 0.8 thresholds the tolerances are: 4 semitones of pitch register, 3 dB of
# level, 6 dB less clarity than the context. Set by calibration against the
# labelled set in tests/continuity/test_calibration.py.
SEMITONES_PER_POINT = 20.0
LEVEL_DB_PER_POINT = 15.0
CLARITY_DB_PER_POINT = 30.0


@dataclass(frozen=True)
class MeasuredThresholds:
    prosody: float = 0.8
    audio_integration: float = 0.8


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def semitones(a_hz: float, b_hz: float) -> float:
    return 12 * math.log2(a_hz / b_hz)


def pitch_score(generated_hz: float | None, context_hz: float | None) -> float | None:
    if generated_hz is None or context_hz is None:
        return None
    return _clamp(1 - abs(semitones(generated_hz, context_hz)) / SEMITONES_PER_POINT)


def level_score(delta_db: float | None) -> float | None:
    if delta_db is None:
        return None
    return _clamp(1 - abs(delta_db) / LEVEL_DB_PER_POINT)


def clarity(x: np.ndarray) -> float | None:
    """How far the speech stands above the quietest part of the clip, in dB."""
    level = signals.speech_level_db(x)
    if level is None:
        return None
    return level - signals.noise_floor_db(x)


def clarity_score(generated_db: float | None, context_db: float | None) -> float | None:
    if generated_db is None or context_db is None:
        return None
    # Only a *less* clear line is penalised; a cleaner one is handled by room tone.
    return _clamp(1 - max(0.0, context_db - generated_db) / CLARITY_DB_PER_POINT)


def context_spans(
    transcript: Transcript, selection: Selection, window: float = CONTEXT_WINDOW,
) -> list[tuple[float, float]]:
    """Runs of the speaker's words near the selection, never inside it."""
    near = tuple(
        w for w in transcript.words
        if w.end > selection.start - window and w.start < selection.end + window
    )
    return speech_runs(Transcript(words=near), selection)


def gap_spans(
    transcript: Transcript, duration: float, min_len: float = 0.15, pad: float = 0.05,
) -> list[tuple[float, float]]:
    """Stretches with no transcribed word — the room between the lines."""
    edges = [Word("", 0.0, 0.0), *transcript.words, Word("", duration, duration)]
    gaps = []
    for before, after in zip(edges, edges[1:]):
        start, end = before.end + pad, after.start - pad
        if end - start >= min_len:
            gaps.append((start, end))
    return gaps


def quiet_part(x: np.ndarray, rate: int, below_db: float) -> np.ndarray:
    """Only the 20 ms frames of `x` quieter than `below_db`.

    Gaps between transcribed words are not reliably silent: Whisper drops
    symbols it cannot spell (the "%" of "20%") as empty words, so the spoken
    "percent" sits in what looks like a gap. Keeping only genuinely quiet
    frames stops speech being laid under the new line as "room tone".
    """
    size = max(1, int(rate * 0.02))
    count = x.size // size
    if count == 0:
        return x[:0]
    frames = x[: count * size].reshape(count, size)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    with np.errstate(divide="ignore"):
        levels = 20 * np.log10(rms)
    return frames[levels < below_db].reshape(-1)


def _read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
        channels = w.getnchannels()
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, rate


def _write_wav(path: Path, x: np.ndarray, rate: int) -> None:
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _concat(path: str, spans: list[tuple[float, float]], rate: int = signals.RATE) -> np.ndarray | None:
    if not spans:
        return None
    return np.concatenate([signals.load(path, s, e, rate=rate) for s, e in spans])


class MeasuredContinuityEngine:
    """Scores prosody and audio integration from the audio itself."""

    measures = ("prosody", "audio_integration")

    def __init__(self, store: ArtifactStore, thresholds: MeasuredThresholds | None = None) -> None:
        self._store = store
        self.thresholds = thresholds or MeasuredThresholds()

    def assess(
        self, source: Source, transcript: Transcript | None, plan: EditPlan,
        audio: MediaArtifact,
    ) -> Assessment:
        warnings: list[str] = []
        src = source.media.path
        transcript = transcript or Transcript(words=())
        context = _concat(src, context_spans(transcript, plan.selection))
        generated, rate = _read_wav(audio.path)

        # ── auto-correct (spec §6: applied before the user sees the candidate) ──
        corrected = generated.copy()
        context_level = signals.speech_level_db(context) if context is not None else None
        generated_level = signals.speech_level_db(signals.load(audio.path))
        if context_level is not None and generated_level is not None:
            gain = context_level - generated_level
            if abs(gain) > MAX_GAIN_DB:
                warnings.append(
                    f"Level is {gain:+.1f} dB off the surrounding speech — too far to correct."
                )
                gain = math.copysign(MAX_GAIN_DB, gain)
            corrected *= 10 ** (gain / 20)

        # Without context speech there is no level to call "quiet" against, so
        # no room tone: unfiltered gaps can hold speech (see `quiet_part`).
        room = None
        if context_level is not None:
            room = _concat(src, gap_spans(transcript, source.duration), rate=rate)
        if room is not None:
            room = quiet_part(room, rate, context_level - ROOM_BELOW_SPEECH_DB)
        if room is not None and room.size >= rate // 10:
            room_db = 20 * math.log10(max(float(np.sqrt(np.mean(room ** 2))), 1e-10))
            if room_db > ROOM_TONE_AUDIBLE_DB:
                # Lay the room's own sound under the new line, so the splice
                # does not drop into studio silence.
                corrected += np.resize(room, corrected.size)

        peak = float(np.max(np.abs(corrected))) if corrected.size else 0.0
        if peak > PEAK_CEILING:
            corrected *= PEAK_CEILING / peak

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrected.wav"
            _write_wav(path, corrected, rate)
            fixed = self._store.put_file(
                source.project_id, path, kind="audio", container="wav",
                duration=audio.duration,
            )

        # ── measure what is left ──
        if context is None:
            warnings.append("Not enough surrounding speech to check continuity.")
            return Assessment(self._report(None, None, warnings), fixed)

        final = signals.load(fixed.path)
        final_f0, context_f0 = signals.median_f0(final), signals.median_f0(context)
        prosody = pitch_score(final_f0, context_f0)
        if prosody is not None and prosody < self.thresholds.prosody:
            warnings.append(
                f"Pitch is {semitones(final_f0, context_f0):+.1f} semitones off the surrounding speech."
            )

        final_level = signals.speech_level_db(final)
        level = level_score(
            final_level - context_level
            if final_level is not None and context_level is not None else None
        )
        clear = clarity_score(clarity(final), clarity(context))
        if clear is not None and clear < self.thresholds.audio_integration:
            warnings.append("The new line is noisier than the surrounding audio.")
        scores = [s for s in (level, clear) if s is not None]
        integration = min(scores) if scores else None

        return Assessment(self._report(prosody, integration, warnings), fixed)

    def _report(
        self, prosody: float | None, integration: float | None, warnings: list[str],
    ) -> ContinuityReport:
        checks = {"prosody": prosody, "audio_integration": integration}
        passed = all(
            value >= getattr(self.thresholds, key)
            for key, value in checks.items() if value is not None
        )
        return ContinuityReport(
            voice_match=None, prosody=prosody, audio_integration=integration, lip_sync=None,
            passed=passed, warnings=tuple(warnings),
            measured=tuple(key for key, value in checks.items() if value is not None),
        )
