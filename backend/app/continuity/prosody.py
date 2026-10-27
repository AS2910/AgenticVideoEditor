"""How a line is said, measured (run 5 item 7): delivery, steering, rejection.

A take can have the speaker's voice and still sound wrong next to their lines:
flatter, faster, pitched where they never go. This module puts numbers on that,
from the audio alone, so a take can be steered toward the speaker, refused when
it falls outside them, and ranked against the other takes.

- **Delivery** of a stretch of speech: its pitch register (median, in semitones
  above 100 Hz), its pitch span (10th to 90th percentile of the voiced frames,
  in semitones: a flat read is narrow, an animated one wide), its speaking rate
  (syllable nuclei a second of speaking time, from the loudness envelope) and
  its pitch contour (the shape of the line's melody, about its own median).
- **The neighbours** are the same speaker's lines either side of the edit. Their
  deliveries give the range a take must sit in (`Bounds`), with margins wide
  enough that the speaker's own lines pass.
- **Prosody distance** is how far a take's contour and rate are from the line it
  replaces (or, without one, from the neighbours): 0 is the same, 1 is at the
  edge of what is noticeable. It is a score in the pick, never a gate alone.
- **Steering** maps a delivery onto the vendor's settings: an animated speaker
  gets a less stable, more expressive read; a take refused as too fast or too
  flat is retaken with the setting that moves it back.

Everything is plain numpy on 16 kHz mono and deterministic. Nothing here may
break a take: unmeasurable audio gives None, and None blocks nothing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.continuity import signals
from app.domain.models import Selection, Transcript, Word

CONTOUR_POINTS = 20
MIN_VOICED = 8            # voiced 10 ms frames needed for a register or span
MIN_LINE_SECONDS = 0.5    # a neighbour shorter than this says nothing about delivery
LINE_GAP = 0.3            # a pause this long ends a line
NEIGHBOUR_WINDOW = 12.0   # seconds either side searched for neighbours
NEIGHBOURS_EACH_SIDE = 3
MIN_NEIGHBOURS = 2        # fewer lines than this: no range, no refusal

# The range a take must sit in, widened past the neighbours' own spread so the
# speaker's own lines pass (checked on the eval clip: every original line of
# p66 sits inside the range of its neighbours).
REGISTER_MARGIN_ST = 2.5
SPAN_LOW, SPAN_HIGH = 0.55, 1.6
RATE_LOW, RATE_HIGH = 0.72, 1.35

# What counts as one point of distance: a contour 3 semitones RMS away from
# the original's shape, or a rate 25% off it.
CONTOUR_ST_PER_POINT = 3.0
RATE_PER_POINT = math.log(1.25)

# Steering (ElevenLabs settings). The span a neutral read has, and the
# stability the vendor defaults to at it; an animated speaker (9 st and up)
# gets the expressive end, a flat one (3 st and under) the steady end.
NEUTRAL_SPAN = 6.0
STABILITY_STEADY, STABILITY_EXPRESSIVE = 0.7, 0.35
STYLE_EXPRESSIVE = 0.2
SPEED_STEP = (0.85, 1.15)   # how far one retake may move the model's speed


@dataclass(frozen=True)
class Delivery:
    register: float | None          # median pitch, semitones above 100 Hz
    span: float | None              # p90 - p10 of voiced pitch, semitones
    rate: float | None              # syllable nuclei per second of speaking time
    level: float | None             # speech level, dBFS
    contour: tuple[float, ...] | None
    seconds: float


@dataclass(frozen=True)
class Bounds:
    register: tuple[float, float] | None
    span: tuple[float, float] | None
    rate: tuple[float, float] | None
    level: float | None             # the neighbours' median speech level
    lines: int


@dataclass(frozen=True)
class Verdict:
    """A take against its target: the distance, what is out of range (in plain
    words, for the warnings), and which way a retake should be steered."""
    distance: float | None
    outside: tuple[str, ...]
    faster: float | None = None      # >1: the take is too fast by this much
    flatter: float | None = None     # >1: the take's span is this much too narrow; <1 too wide


def _st(hz: np.ndarray | float) -> np.ndarray | float:
    return 12 * np.log2(np.asarray(hz) / 100.0)


def f0_track(x: np.ndarray) -> np.ndarray:
    """Pitch (Hz) per 10 ms hop, NaN where unvoiced or quiet. The same
    autocorrelation as `signals.median_f0`, kept per frame."""
    frames = signals._frames(np.asarray(x, dtype=np.float32), signals.PITCH_FRAME).astype(np.float64)
    out = np.full(frames.shape[0], np.nan)
    if frames.shape[0] == 0:
        return out
    frames -= frames.mean(axis=1, keepdims=True)
    energy = np.sum(frames ** 2, axis=1)
    keep = signals._active(signals._to_db(np.sqrt(energy / signals.PITCH_FRAME)))
    idx = np.flatnonzero(keep)
    if idx.size == 0:
        return out
    sub = frames[idx]
    lags = np.arange(int(signals.RATE / signals.F0_MAX), int(signals.RATE / signals.F0_MIN) + 2)
    corr = np.empty((sub.shape[0], lags.size))
    for i, lag in enumerate(lags):
        a, b = sub[:, :-lag], sub[:, lag:]
        denom = np.sqrt(np.sum(a * a, axis=1) * np.sum(b * b, axis=1))
        corr[:, i] = np.sum(a * b, axis=1) / np.where(denom > 0, denom, np.inf)
    for row_i, row in zip(idx, corr):
        peak = row.max()
        if peak < signals.VOICING:
            continue
        i = np.flatnonzero(row >= 0.9 * peak)[0]
        while i + 1 < row.size and row[i + 1] > row[i]:
            i += 1
        lag = float(lags[i])
        if 0 < i < row.size - 1:
            y0, y1, y2 = row[i - 1], row[i], row[i + 1]
            d = y0 - 2 * y1 + y2
            if d != 0:
                lag += 0.5 * (y0 - y2) / d
        out[row_i] = signals.RATE / lag
    return out


def syllable_rate(x: np.ndarray) -> float | None:
    """Syllable nuclei a second of speaking time: peaks of the smoothed
    loudness envelope at least 3 dB above the dip before them, at least 100 ms
    apart, within 25 dB of the loudest frame."""
    levels = signals.frame_levels_db(np.asarray(x, dtype=np.float32))
    if levels.size < 10:
        return None
    k = 5   # 50 ms smoothing
    smooth = np.convolve(levels, np.ones(k) / k, mode="same")
    active = signals._active(levels)
    speaking = active.sum() * signals.HOP / signals.RATE
    if speaking < 0.25:
        return None
    floor = smooth.max() - 25.0
    peaks, last, dip = 0, -100, smooth[0]
    for i in range(1, len(smooth) - 1):
        dip = min(dip, smooth[i])
        if smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1] and smooth[i] > floor \
                and smooth[i] - dip >= 3.0 and i - last >= 10:
            peaks += 1
            last, dip = i, smooth[i]
    return peaks / speaking if peaks else None


def _contour(track: np.ndarray) -> tuple[float, ...] | None:
    voiced = np.flatnonzero(~np.isnan(track))
    if voiced.size < MIN_VOICED:
        return None
    st = _st(track[voiced])
    st = st - np.median(st)
    # Short median smoothing: one octave error should not bend the shape.
    if st.size >= 5:
        st = np.array([np.median(st[max(0, i - 2):i + 3]) for i in range(st.size)])
    pos = (voiced - voiced[0]) / max(1, voiced[-1] - voiced[0])
    grid = np.linspace(0, 1, CONTOUR_POINTS)
    return tuple(float(v) for v in np.interp(grid, pos, st))


def measure(x: np.ndarray) -> Delivery:
    """The delivery of one stretch of 16 kHz mono speech."""
    x = np.asarray(x, dtype=np.float32)
    seconds = x.size / signals.RATE
    track = f0_track(x)
    voiced = track[~np.isnan(track)]
    register = span = None
    if voiced.size >= MIN_VOICED:
        st = _st(voiced)
        register = float(np.median(st))
        span = float(np.percentile(st, 90) - np.percentile(st, 10))
    return Delivery(register, span, syllable_rate(x), signals.speech_level_db(x), _contour(track), seconds)


def lines_near(transcript: Transcript, selection: Selection, speaker: str | None,
               window: float = NEIGHBOUR_WINDOW) -> list[tuple[float, float]]:
    """The speaker's lines either side of the selection, nearest first on each
    side, never overlapping it: runs of words split at pauses of LINE_GAP."""
    words = [w for w in transcript.words
             if (speaker is None or w.speaker == speaker)
             and not (w.end > selection.start and w.start < selection.end)
             and w.end > selection.start - window and w.start < selection.end + window]
    lines: list[list[Word]] = []
    for w in words:
        crosses = lines and lines[-1][-1].end <= selection.start <= w.start
        if lines and w.start - lines[-1][-1].end < LINE_GAP and not crosses:
            lines[-1].append(w)
        else:
            lines.append([w])
    spans = [(ln[0].start, ln[-1].end) for ln in lines if ln[-1].end - ln[0].start >= MIN_LINE_SECONDS]
    before = [s for s in spans if s[1] <= selection.start][::-1][:NEIGHBOURS_EACH_SIDE]
    after = [s for s in spans if s[0] >= selection.end][:NEIGHBOURS_EACH_SIDE]
    return before + after


def bounds(neighbours: list[Delivery]) -> Bounds:
    """The range a take must sit in, from the neighbours' deliveries; a measure
    with too few lines behind it is None (and refuses nothing)."""
    def spread(values, low, high, mul):
        vals = [v for v in values if v is not None]
        if len(vals) < MIN_NEIGHBOURS:
            return None
        return (min(vals) * low, max(vals) * high) if mul else (min(vals) - low, max(vals) + high)

    levels = [d.level for d in neighbours if d.level is not None]
    return Bounds(
        register=spread([d.register for d in neighbours], REGISTER_MARGIN_ST, REGISTER_MARGIN_ST, False),
        span=spread([d.span for d in neighbours], SPAN_LOW, SPAN_HIGH, True),
        rate=spread([d.rate for d in neighbours], RATE_LOW, RATE_HIGH, True),
        level=float(np.median(levels)) if levels else None,
        lines=len(neighbours),
    )


def distance(take: Delivery, reference: Delivery | None, neighbours: list[Delivery]) -> float | None:
    """Pitch contour plus rate, against the replaced line (or, for the rate,
    the neighbours' median when the line has none). 0 is the same delivery."""
    terms = []
    if reference is not None and take.contour is not None and reference.contour is not None:
        diff = np.asarray(take.contour) - np.asarray(reference.contour)
        terms.append(float(np.sqrt(np.mean(diff ** 2))) / CONTOUR_ST_PER_POINT)
    target = reference.rate if reference is not None and reference.rate else None
    if target is None:
        rates = [d.rate for d in neighbours if d.rate]
        target = float(np.median(rates)) if rates else None
    if take.rate and target:
        terms.append(abs(math.log(take.rate / target)) / RATE_PER_POINT)
    return round(sum(terms) / len(terms), 4) if terms else None


def judge(take: Delivery, reference: Delivery | None, neighbours: list[Delivery]) -> Verdict:
    """The take's distance, and what of it falls outside the neighbours' range."""
    b = bounds(neighbours)
    outside: list[str] = []
    faster = flatter = None
    if b.rate and take.rate:
        lo, hi = b.rate
        if take.rate > hi:
            outside.append(f"Said faster than the lines around it ({take.rate:.1f} syllables a second; they run {lo:.1f} to {hi:.1f}).")
            faster = take.rate / ((lo + hi) / 2)
        elif take.rate < lo:
            outside.append(f"Said slower than the lines around it ({take.rate:.1f} syllables a second; they run {lo:.1f} to {hi:.1f}).")
            faster = take.rate / ((lo + hi) / 2)
    if b.span and take.span is not None:
        lo, hi = b.span
        if take.span < lo:
            outside.append(f"Flatter than the lines around it (pitch moves {take.span:.1f} semitones; they move {lo:.1f} to {hi:.1f}).")
            flatter = ((lo + hi) / 2) / max(take.span, 0.5)
        elif take.span > hi:
            outside.append(f"More sing-song than the lines around it (pitch moves {take.span:.1f} semitones; they move {lo:.1f} to {hi:.1f}).")
            flatter = ((lo + hi) / 2) / take.span
    if b.register and take.register is not None:
        lo, hi = b.register
        if not lo <= take.register <= hi:
            where = "higher" if take.register > hi else "lower"
            outside.append(f"Pitched {where} than the lines around it.")
    return Verdict(distance(take, reference, neighbours), tuple(outside), faster, flatter)


def score(distance_: float | None) -> float | None:
    """The distance as a 0-1 score, 0.8 at one point: the scale the other
    scores of the pick use, so it ranks beside them."""
    if distance_ is None:
        return None
    return max(0.0, min(1.0, 1.0 - 0.2 * distance_))


def reference_settings(reference: Delivery | None, neighbours: list[Delivery]) -> dict | None:
    """Vendor settings for a first take that follows the speaker: the original
    line's pitch span (or the neighbours' median) mapped onto stability, and a
    little style for an animated read. None when nothing was measurable, or the
    speaker is near neutral (the vendor's defaults already fit)."""
    span = reference.span if reference is not None and reference.span is not None else None
    if span is None:
        spans = [d.span for d in neighbours if d.span is not None]
        span = float(np.median(spans)) if spans else None
    if span is None or abs(span - NEUTRAL_SPAN) < 1.0:
        return None
    t = max(0.0, min(1.0, (span - 3.0) / 6.0))     # 0 at 3 st, 1 at 9 st
    stability = STABILITY_STEADY + (STABILITY_EXPRESSIVE - STABILITY_STEADY) * t
    out = {"stability": round(stability, 2)}
    if t > 0.5:
        out["style"] = round(STYLE_EXPRESSIVE * (t - 0.5) * 2, 2)
    return out


def steer(settings: dict | None, verdict: Verdict) -> dict | None:
    """The settings for a retake of a take judged out of range: slower when it
    ran fast, more expressive when flat, steadier when sing-song. None when the
    verdict gives nothing to move."""
    if verdict.faster is None and verdict.flatter is None:
        return None
    out = dict(settings or {})
    if verdict.faster is not None:
        step = max(SPEED_STEP[0], min(SPEED_STEP[1], 1.0 / verdict.faster))
        out["speed"] = round(max(0.7, min(1.2, out.get("speed", 1.0) * step)), 2)
    if verdict.flatter is not None:
        stability = out.get("stability", 0.5)
        if verdict.flatter > 1:
            out["stability"] = round(max(0.2, stability - 0.15), 2)
            out["style"] = round(min(0.5, out.get("style", 0.0) + 0.1), 2)
        else:
            out["stability"] = round(min(0.9, stability + 0.15), 2)
    return out


def same_words(transcript: Transcript | None, selection: Selection, text: str) -> bool:
    """Whether `text` says exactly the words already spoken in the selection
    (a change of voice only): then the original line itself can be the take."""
    if transcript is None:
        return False
    norm = lambda s: [t.strip(".,!?;:\"'").lower() for t in s.split() if t.strip(".,!?;:\"'")]   # noqa: E731
    said = [w.text for w in transcript.words if w.start >= selection.start - 0.02 and w.end <= selection.end + 0.02]
    return bool(said) and norm(" ".join(said)) == norm(text)
