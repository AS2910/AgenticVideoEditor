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
- **Voice match** (SIM-o) and **naturalness** (UTMOS) come from open models
  (Phase 15d, extra `measure`); without them they stay None and block nothing.
- Lip-sync stays None until Phase 17.
- **Delivery** (run 5 item 7, `continuity.prosody`): the take's pitch span,
  register and speaking rate against the same speaker's lines either side, and
  a prosody distance (pitch contour plus rate) to the line it replaces. A take
  outside the neighbours' range is refused (so it is retaken, steered back) and
  the distance ranks takes in the pick. A line asked for in another delivery
  ("more excited", or Voltage's own settings) is measured but never refused
  for differing: the difference was the point.
- **The room** (run 5 item 7): when the speech around the line is clean enough
  to hear the room in, the take is EQ'd toward the speaker's spectrum and given
  the room's reverb here, so the proposal already sounds in place; the render
  then does not add them again (`EditPlan.roomed`). A noisy or music-backed
  clip is left to the render's stems path, as before. Room tone is laid under
  the line as a crossfaded loop, not a hard-tiled one.
"""
from __future__ import annotations

import math
import os
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.continuity import prosody as tone, signals, similarity
from app.continuity.engine import Assessment
from app.media import room as roommod
from app.domain.models import (
    ContinuityReport, EditPlan, MediaArtifact, Selection, Source, Transcript, Word,
)
from app.domain.transcript import speaker_of
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

# The speaker's own speech used as the identity reference: a wider window than
# the pitch context, because a speaker embedding settles on more speech.
VOICE_WINDOW = 30.0

# Run 5 item 7: the room is matched on the take only when the speech around it
# stands this far above the quietest part of that stretch (a clean room, or a
# bed far under the voice: EQ toward a loud mix of voice and music would colour
# the voice). Seconds of the original either side read for this and the reverb.
CLEAN_ROOM_DB = 25.0
ROOM_READ_SECONDS = 8.0
LOOP_FADE = 0.03            # crossfade between repeats of the room tone, seconds


def tone_on() -> bool:
    """Run 5 item 7's delivery and room work, on unless AVE_VOICE_TONE=0."""
    return os.environ.get("AVE_VOICE_TONE", "1").strip().lower() not in {"0", "false", "no", "off"}


def reference_on() -> bool:
    """Whether the first take follows the speaker's measured delivery (AVE_VOICE_TONE_REFERENCE=1)."""
    return os.environ.get("AVE_VOICE_TONE_REFERENCE", "").strip().lower() in {"1", "true", "yes", "on"}


def loop_room(room: np.ndarray, size: int, rate: int) -> np.ndarray:
    """`room` repeated to `size` samples with equal-power crossfades at each
    join, so the room tone under a line has no click every repeat."""
    fade = min(int(LOOP_FADE * rate), room.size // 4)
    if room.size == 0 or size <= 0:
        return np.zeros(max(0, size), dtype=np.float32)
    if fade < 2 or room.size >= size:
        return np.resize(room, size).astype(np.float32)
    ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))
    out = np.zeros(size + room.size, dtype=np.float32)
    step, at = room.size - fade, 0
    while at < size:
        piece = room.astype(np.float32).copy()
        if at:
            piece[:fade] *= ramp
        piece[-fade:] *= ramp[::-1]
        out[at:at + room.size] += piece
        at += step
    return out[:size]


@dataclass(frozen=True)
class MeasuredThresholds:
    prosody: float = 0.8
    audio_integration: float = 0.8
    voice_match: float = 0.75   # SIM-o; a same-speaker take scores ~0.85+, a stranger ~0.5
    naturalness: float = 3.0    # MOS, 1-5; below 3 is audibly synthetic


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


# Run 5 item 8 (evals/messy, phone_dropouts): dropped packets read 50 dB and
# more under the speech. Counted as the floor, they made a phone clip's context
# look far clearer than it sounds, and a perfect take failed as noisier. A floor
# is read only from frames within this of the speech: anything quieter is a
# hole in the sound, not a room, and as clean as clarity needs to know.
FLOOR_RANGE_DB = 40.0


def clarity(x: np.ndarray) -> float | None:
    """How far the speech stands above the quietest part of the clip, in dB
    (the quietest part that is a room at all: dropouts are not a floor)."""
    level = signals.speech_level_db(x)
    if level is None:
        return None
    levels = signals.frame_levels_db(x)
    heard = levels[levels > level - FLOOR_RANGE_DB]
    floor = float(np.percentile(heard, 10)) if heard.size else level - FLOOR_RANGE_DB
    return level - floor


def clarity_score(generated_db: float | None, context_db: float | None) -> float | None:
    if generated_db is None or context_db is None:
        return None
    # Only a *less* clear line is penalised; a cleaner one is handled by room tone.
    return _clamp(1 - max(0.0, context_db - generated_db) / CLARITY_DB_PER_POINT)


def context_spans(
    transcript: Transcript, selection: Selection, window: float = CONTEXT_WINDOW,
) -> list[tuple[float, float]]:
    """Runs of the speaker's words near the selection, never inside it.

    When the selection is one speaker's words (Phase 11), only that speaker's
    words count: another speaker's pitch is not the reference for this one.
    """
    speaker = speaker_of(transcript, selection)
    near = tuple(
        w for w in transcript.words
        if w.end > selection.start - window and w.start < selection.end + window
        and (speaker is None or w.speaker == speaker)
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


def directed(plan: EditPlan) -> bool:
    """Whether the line was asked for in a delivery of its own (UX-1's words,
    or Voltage's vendor settings): then differing from the speaker is the point."""
    return bool(plan.delivery or plan.voice_settings)


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
    """Scores prosody, audio integration, voice match and naturalness from the audio itself.

    `match(reference, candidate)` and `mos(candidate)` default to the models of
    `similarity` when the `measure` extra is usable, and to nothing when not;
    tests inject fakes. `measures` lists only what is live.
    """

    def __init__(
        self, store: ArtifactStore, thresholds: MeasuredThresholds | None = None, *,
        match: Callable[[Path, Path], float | None] | None = None,
        mos: Callable[[Path], float | None] | None = None,
        tone: bool | None = None, room: bool | None = None, reference: bool | None = None,
    ) -> None:
        self._store = store
        self.thresholds = thresholds or MeasuredThresholds()
        # Run 5 item 7: delivery (steer, refuse, rank) and the room on the take.
        self.tone = tone_on() if tone is None else tone
        # Its two parts that change the take itself, apart (the eval's ablations).
        self.room = self.tone if room is None else room
        # The first take in settings that follow the speaker: off unless
        # AVE_VOICE_TONE_REFERENCE=1 (run 5 item 7's eval: no gain past noise).
        self.use_reference = (self.tone and reference_on()) if reference is None else reference
        live = similarity.available()
        self._match = match or (similarity.speaker_similarity if live else None)
        self._mos = mos or (similarity.naturalness if live else None)
        self.measures = (
            "prosody", "audio_integration",
            *(("voice_match",) if self._match else ()),
            *(("naturalness",) if self._mos else ()),
        )

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
                    f"Level is {gain:+.1f} dB off the surrounding speech, too far to correct."
                )
                gain = math.copysign(MAX_GAIN_DB, gain)
            corrected *= 10 ** (gain / 20)

        # Run 5 item 7: the speaker's spectrum and room on the take itself.
        roomed = False
        # The take as made (level-corrected, before the room): what clarity is
        # read on. The room's EQ can take a take's own hiss down with it, and
        # a noisy take must not pass because the room was put on it.
        dry = corrected.copy()
        if self.room and context is not None and plan.mix != "layer":
            corrected, roomed = self._in_room(src, transcript, plan, corrected, rate, context)

        # Without context speech there is no level to call "quiet" against, so
        # no room tone: unfiltered gaps can hold speech (see `quiet_part`).
        room = None
        # A layered line plays over the original sound, room and all.
        if context_level is not None and plan.mix != "layer":
            room = _concat(src, gap_spans(transcript, source.duration), rate=rate)
        if room is not None:
            room = quiet_part(room, rate, context_level - ROOM_BELOW_SPEECH_DB)
        if room is not None and room.size >= rate // 10:
            room_db = 20 * math.log10(max(float(np.sqrt(np.mean(room ** 2))), 1e-10))
            if room_db > ROOM_TONE_AUDIBLE_DB:
                # Lay the room's own sound under the new line, so the splice
                # does not drop into studio silence.
                tone_bed = (loop_room(room, corrected.size, rate) if self.tone
                            else np.resize(room, corrected.size))
                corrected += tone_bed
                dry += tone_bed

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
        natural = self._mos(Path(fixed.path)) if self._mos else None
        if context is None:
            warnings.append("Not enough surrounding speech to check continuity.")
            return Assessment(self._report(None, None, warnings, naturalness=natural), fixed, roomed=roomed)

        final = signals.load(fixed.path)
        final_f0, context_f0 = signals.median_f0(final), signals.median_f0(context)
        # The pitch register is a check on a replaced line against the same
        # speaker's speech around it. An added line (over the picture, or the
        # picture held) is often another voice on purpose, so its register is
        # measured but not held against it (20d).
        added = plan.mix in ("layer", "concatenate")
        prosody = pitch_score(final_f0, context_f0)
        if prosody is not None and prosody < self.thresholds.prosody and not added:
            warnings.append(
                f"Pitch is {semitones(final_f0, context_f0):+.1f} semitones off the surrounding speech."
            )
        if added:
            prosody = None

        final_level = signals.speech_level_db(final)
        level = level_score(
            final_level - context_level
            if final_level is not None and context_level is not None else None
        )
        heard = final
        if roomed:
            with tempfile.TemporaryDirectory() as tmp:
                _write_wav(Path(tmp) / "dry.wav", dry, rate)
                heard = signals.load(Path(tmp) / "dry.wav")
        clear = clarity_score(clarity(heard), clarity(context))
        if clear is not None and clear < self.thresholds.audio_integration:
            warnings.append("The new line is noisier than the surrounding audio.")
        scores = [s for s in (level, clear) if s is not None]
        integration = min(scores) if scores else None

        voice = self._voice_match(source, transcript, plan, Path(fixed.path))
        verdict, refused = None, False
        if self.tone:
            verdict = self._delivery(src, transcript, plan, signals.load(audio.path))
            # A directed line (a delivery asked for, or Voltage's own settings)
            # and an added line are measured, never refused for differing.
            if verdict is not None and verdict.outside and not added and not directed(plan):
                warnings.extend(verdict.outside)
                refused = True
        return Assessment(
            self._report(prosody, integration, warnings, voice_match=voice, naturalness=natural,
                         prosody_distance=verdict.distance if verdict is not None else None, refused=refused),
            fixed, roomed=roomed, delivery=verdict,
        )

    def _in_room(self, src: str, transcript: Transcript, plan: EditPlan, take: np.ndarray,
                 rate: int, context: np.ndarray) -> tuple[np.ndarray, bool]:
        """The take EQ'd toward the speaker's own speech and given the room's
        reverb, when the speech around it is clean enough to hear the room in.
        Same length and level either way."""
        try:
            sel = plan.selection
            around = signals.load(src, max(0.0, sel.start - ROOM_READ_SECONDS), sel.end + ROOM_READ_SECONDS)
            level = signals.speech_level_db(around)
            if level is None or level - signals.noise_floor_db(around) < CLEAN_ROOM_DB:
                return take, False
            speech = _concat(src, context_spans(transcript, plan.selection), rate=rate)
            around = [(a, b) for a, b in ((max(0.0, sel.start - ROOM_READ_SECONDS), sel.start),
                                          (sel.end, sel.end + ROOM_READ_SECONDS)) if b - a >= 1.0]
            profile = None
            for a, b in sorted(around, key=lambda s: s[0] - s[1]):   # the longer stretch first
                profile = roommod.estimate_reverb(signals.load(src, a, b, rate=rate), rate)
                if profile is not None:
                    break
            out = take
            if speech is not None and speech.size:
                out = roommod.spectral_match(out, speech, rate)
            if profile is not None:
                out = roommod.match_room(out, profile, rate)
            return out.astype(np.float32), True
        except Exception:  # noqa: BLE001 - a room that cannot be read leaves the take as it was
            return take, False

    def _delivery(self, src: str, transcript: Transcript, plan: EditPlan, take: np.ndarray):
        """The take's delivery against the line it replaces and the speaker's
        lines either side (`prosody.judge`), or None when nothing could be read."""
        try:
            neighbours, reference = self.deliveries(src, transcript, plan)
            return tone.judge(tone.measure(take), reference, neighbours)
        except Exception:  # noqa: BLE001 - delivery is a score, never a reason a take fails to exist
            return None

    def deliveries(self, src: str, transcript: Transcript, plan: EditPlan):
        """(the neighbours' deliveries, the replaced line's delivery or None)."""
        sel = plan.selection
        spans = tone.lines_near(transcript, sel, speaker_of(transcript, sel))
        neighbours = [tone.measure(signals.load(src, a, b)) for a, b in spans]
        reference = None
        if plan.mix not in ("layer", "concatenate") and sel.end - sel.start >= tone.MIN_LINE_SECONDS:
            reference = tone.measure(signals.load(src, sel.start, sel.end))
        return neighbours, reference

    def reference(self, source: Source, transcript: Transcript | None, plan: EditPlan) -> dict | None:
        """Vendor settings for a first take that follows the speaker's own
        delivery (`prosody.reference_settings`), or None: tone off, a directed
        or added line, or nothing measurable."""
        if not (self.tone and self.use_reference) or transcript is None or directed(plan) or plan.mix != "replace":
            return None
        try:
            neighbours, ref = self.deliveries(source.media.path, transcript, plan)
            return tone.reference_settings(ref, neighbours)
        except Exception:  # noqa: BLE001
            return None

    def _voice_match(
        self, source: Source, transcript: Transcript, plan: EditPlan, take: Path,
    ) -> float | None:
        """SIM-o of the take against the speaker's own speech outside the selection."""
        if self._match is None:
            return None
        spans = context_spans(transcript, plan.selection, window=VOICE_WINDOW)
        reference = _concat(source.media.path, spans)
        if reference is None:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.wav"
            _write_wav(path, reference, signals.RATE)
            return self._match(path, take)

    def _report(
        self, prosody: float | None, integration: float | None, warnings: list[str],
        *, voice_match: float | None = None, naturalness: float | None = None,
        prosody_distance: float | None = None, refused: bool = False,
    ) -> ContinuityReport:
        if voice_match is not None and voice_match < self.thresholds.voice_match:
            warnings.append(
                "Sounds less like the speaker than it should "
                f"(match {voice_match:.2f}, wants {self.thresholds.voice_match:.2f})."
            )
        if naturalness is not None and naturalness < self.thresholds.naturalness:
            warnings.append(
                "Sounds less natural than it should "
                f"(naturalness {naturalness:.1f}, wants {self.thresholds.naturalness:.1f})."
            )
        checks = {
            "voice_match": voice_match, "prosody": prosody,
            "audio_integration": integration, "naturalness": naturalness,
        }
        passed = not refused and all(
            value >= getattr(self.thresholds, key)
            for key, value in checks.items() if value is not None
        )
        return ContinuityReport(
            voice_match=voice_match, prosody=prosody, audio_integration=integration, lip_sync=None,
            passed=passed, warnings=tuple(warnings), naturalness=naturalness,
            measured=tuple(key for key, value in checks.items() if value is not None)
            + (("prosody_distance",) if prosody_distance is not None else ()),
            prosody_distance=prosody_distance,
        )
