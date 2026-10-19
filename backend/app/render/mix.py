"""Role-based, relative mixing (2026-10-20).

An added line is not given a gain; it is given a role, and its level follows
from what plays with it, measured as loudness (LUFS, `media.loudness`):

- a Voice sits at the clip's own speech loudness (measured from the
  speaker's words; a project default on a clip with no speech);
- an Effect sits at the same level;
- a Bed sits `bed_under_db` under the loudest voice playing in its span, or,
  with no voice there, `bed_alone_db` under the speech level, so it plays
  nearly full. A bed ducks a further `duck_db` while any voice speaks (the
  original's words or an added voice), with gentle ramps, and fades in and out.

An added voice over the original's music ducks that music: the separated bed
when the 15c stems are there, else the whole source by up to
`source_duck_max_db`. Then every voice is checked: its loudness against
everything else over its span. Under `clear_db` the row is told which sound
covers it. The user's fine-tune (`offset_db`) is applied last.

Pure: arrays in, arrays and a report out. `compose` calls it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from app.domain.models import role_of
from app.media import loudness as L

FRAME = 0.01


@dataclass(frozen=True)
class MixSettings:
    voice_default_lufs: float = -18.0     # a clip with no speech: where a voice sits
    bed_under_db: float = 15.0            # a bed under the loudest voice (12 to 18)
    bed_alone_db: float = 6.0             # a bed with no voice in its span, under the speech level
    duck_db: float = 6.0                  # a bed's extra dip while words play
    attack: float = 0.15
    release: float = 0.4
    source_duck_max_db: float = 8.0       # the whole source, under an added voice, with no stems
    stem_duck_max_db: float = 15.0        # the separated bed, under an added voice
    bed_fade: float = 0.3
    clear_db: float = 10.0                # a voice this far over everything else is heard
    export_lufs: float | None = None      # the whole mix normalised here (None: as mixed)
    true_peak_db: float = -1.0


@dataclass
class LineReport:
    """What the mix did with one line, for the row and for Voltage."""
    edit_id: str
    candidate_id: str
    role: str
    start: float
    end: float
    gain_db: float = 0.0
    level_lufs: float | None = None       # how loud it plays
    under_db: float | None = None         # a bed: how far under the voices in its span
    alone: bool = False                   # a bed with no speech in its span
    ducks: bool = False                   # a bed that dips while words play
    ratio_db: float | None = None         # a voice: over everything else in its span
    covered_by: str | None = None
    flag: str | None = None

    def as_dict(self) -> dict:
        r = lambda v: None if v is None else round(v, 1)   # noqa: E731
        return {"edit_id": self.edit_id, "candidate_id": self.candidate_id, "role": self.role,
                "start": round(self.start, 3), "end": round(self.end, 3), "gain_db": r(self.gain_db),
                "level_lufs": r(self.level_lufs), "under_db": r(self.under_db), "alone": self.alone,
                "ducks": self.ducks, "ratio_db": r(self.ratio_db), "covered_by": self.covered_by, "flag": self.flag}


@dataclass
class MixResult:
    audio: np.ndarray
    voice_lufs: float
    reports: list[LineReport] = field(default_factory=list)
    gains: dict[str, float] = field(default_factory=dict)   # edit_id -> linear gain, for lines played in inserted time


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _mask(spans: Sequence[tuple[float, float]], samples: int, rate: int, lo: int = 0) -> np.ndarray:
    m = np.zeros(samples, dtype=bool)
    for a, b in spans:
        i0, i1 = max(0, round(a * rate) - lo), min(samples, round(b * rate) - lo)
        if i1 > i0:
            m[i0:i1] = True
    return m


def _frames(mask: np.ndarray, rate: int) -> np.ndarray:
    f = int(rate * FRAME)
    n = len(mask) // f
    return mask[: n * f].reshape(n, f).any(axis=1) if n else np.zeros(0, dtype=bool)


def _fades(samples: int, seconds: float, rate: int) -> np.ndarray:
    env = np.ones(samples)
    k = min(int(seconds * rate), samples // 2)
    if k:
        ramp = np.sin(np.linspace(0, np.pi / 2, k)) ** 2
        env[:k] = ramp
        env[-k:] = ramp[::-1]
    return env


def _name(edit) -> str:
    text = (edit.plan.new_text or "").strip().strip("[]").strip()
    return f"“{text}”" if text else "another line"


def as_shot(edit) -> bool:
    """A line of the original speech the arrangement moved: it keeps the
    level it was recorded at; it is a voice, but not one the mix sets."""
    return str(getattr(edit, "edit_id", "")).startswith("arr-")


def speech_level(base: np.ndarray, words: Sequence[tuple[float, float]], settings: MixSettings, rate: int = L.RATE) -> float:
    """The clip's own speech loudness, from the speaker's words; the default without speech."""
    mask = _mask(words, len(base), rate)
    if not mask.any():
        return settings.voice_default_lufs
    level = L.loudness(base, rate, mask)
    return level if level > L.SILENCE else settings.voice_default_lufs


def standalone_gain_db(edit, audio: np.ndarray, voice_lufs: float, settings: MixSettings, rate: int = L.RATE) -> float:
    """The gain for a line played in time of its own (an insert, a held
    frame): nothing else speaks there, so a bed plays nearly full."""
    own = L.loudness(audio, rate)
    if own <= L.SILENCE:
        return 0.0
    role = role_of(edit.plan)
    target = voice_lufs - settings.bed_alone_db if role == "bed" else voice_lufs
    return target - own + float(edit.plan.offset_db or 0.0)


def mix(
    base: np.ndarray,
    layers: Sequence,
    audio_of: Callable[[object], np.ndarray],
    words: Sequence[tuple[float, float]],
    settings: MixSettings,
    bed: np.ndarray | None = None,
    lines: Sequence[tuple[float, float]] = (),
    rate: int = L.RATE,
) -> MixResult:
    """`base` (the source with its replaced lines spliced in) with every
    layer mixed in by its role. `words` are the spans of the original speech,
    `bed` the separated accompaniment (15c) when there are stems, `lines` the
    original spoken lines, checked too when a layer plays over them."""
    n, channels = base.shape
    voice_lufs = speech_level(base, words, settings, rate)
    words_mask = _mask(words, n, rate)
    out_base = base.astype(np.float64).copy()

    # Every layer's take, cut to its span.
    placed = []
    for e in layers:
        i0 = min(round(e.plan.selection.start * rate), n)
        i1 = min(round(e.plan.selection.end * rate), n)
        if i1 <= i0:
            continue
        take = audio_of(e)[: i1 - i0].astype(np.float64)
        if len(take) < i1 - i0:
            take = np.vstack([take, np.zeros((i1 - i0 - len(take), channels))])
        placed.append((e, i0, i1, take))

    reports: dict[str, LineReport] = {}
    pieces: dict[str, tuple[int, int, np.ndarray]] = {}
    voice_frames = _frames(words_mask, rate).copy()
    voices = []
    # Voices and effects first: they set the level the beds sit under.
    for e, i0, i1, take in placed:
        role = role_of(e.plan)
        if role == "bed":
            continue
        own = L.loudness(take, rate)
        g = 0.0 if own <= L.SILENCE or as_shot(e) else voice_lufs - own + float(e.plan.offset_db or 0.0)
        piece = take * L.gain(g) * _fades(len(take), 0.01, rate)[:, None]
        pieces[e.edit_id] = (i0, i1, piece)
        level = L.loudness(piece, rate)
        reports[e.edit_id] = LineReport(e.edit_id, e.candidate_id, role, i0 / rate, i1 / rate, g, level)
        if role == "voice":
            active = L.frames_active(take, rate)
            f0 = int(i0 / (rate * FRAME))
            m = min(len(active), len(voice_frames) - f0)
            if m > 0:
                voice_frames[f0:f0 + m] |= active[:m]
            voices.append((e, i0, i1, level, active))

    # An added voice over the original's music: the music dips under it.
    if voices:
        duck_db = np.zeros(len(voice_frames))
        for e, i0, i1, level, active in voices:
            span = slice(i0, i1)
            if words_mask[span].mean() > 0.2:
                continue                                    # speech under it: two voices, nothing to duck
            under = bed[span] if bed is not None else out_base[span]
            here = L.loudness(under, rate)
            if here <= L.SILENCE:
                continue
            cap = settings.stem_duck_max_db if bed is not None else settings.source_duck_max_db
            amount = float(np.clip(here - (level - settings.bed_under_db), 0.0, cap))
            f0 = int(i0 / (rate * FRAME))
            m = min(len(active), len(duck_db) - f0)
            if m > 0 and amount > 0:
                duck_db[f0:f0 + m] = np.minimum(duck_db[f0:f0 + m], np.where(active[:m], -amount, 0.0))
        if duck_db.min() < 0:
            env = _duck_curve(duck_db, n, rate, settings)
            if bed is not None:
                out_base = out_base - bed.astype(np.float64) * (1.0 - env)[:, None]
            else:
                out_base = out_base * env[:, None]

    # Beds: under the loudest voice in their span, dipping while words play.
    for e, i0, i1, take in placed:
        if role_of(e.plan) != "bed":
            continue
        own = L.loudness(take, rate)
        span_frames = slice(int(i0 / (rate * FRAME)), int(i1 / (rate * FRAME)))
        levels = []
        if words_mask[i0:i1].any():
            levels.append(L.loudness(out_base[i0:i1], rate, words_mask[i0:i1]))
        levels += [lv for v, a, b, lv, _ in voices if a < i1 and i0 < b]
        levels = [lv for lv in levels if lv > L.SILENCE]
        alone = not levels
        target = (voice_lufs - settings.bed_alone_db) if alone else max(levels) - settings.bed_under_db
        g = 0.0 if own <= L.SILENCE else target - own + float(e.plan.offset_db or 0.0)
        env = _fades(len(take), settings.bed_fade, rate) * L.gain(g)
        talking = voice_frames[span_frames]
        ducks = bool(talking.any())
        if ducks:
            env = env * L.ramp_envelope(talking, -settings.duck_db, len(take), rate, settings.attack, settings.release, FRAME)
        piece = take * env[:, None]
        pieces[e.edit_id] = (i0, i1, piece)
        level = L.loudness(take * L.gain(g), rate)
        reports[e.edit_id] = LineReport(e.edit_id, e.candidate_id, "bed", i0 / rate, i1 / rate, g, level,
                                        under_db=None if alone else max(levels) - level, alone=alone, ducks=ducks)

    out = out_base.copy()   # out_base stays the source alone, to tell it apart from the layers
    for i0, i1, piece in pieces.values():
        out[i0:i1] += piece

    # Is every voice heard? Its loudness against everything else in its span.
    for e, i0, i1, level, active in voices:
        mask = np.repeat(active, int(rate * FRAME))[: i1 - i0]
        if len(mask) < i1 - i0:
            mask = np.concatenate([mask, np.zeros(i1 - i0 - len(mask), dtype=bool)])
        if not mask.any():
            continue
        own = pieces[e.edit_id][2]
        rest = out[i0:i1] - own
        ratio = L.loudness(own, rate, mask) - L.loudness(rest, rate, mask)
        rep = reports[e.edit_id]
        rep.ratio_db = ratio
        if ratio < settings.clear_db:
            cover, name = _loudest_other(e, i0, i1, mask, pieces, layers, out_base, rate)
            rep.covered_by = cover
            rep.flag = (f"{name} covers this line at {_clock(i0 / rate)}; "
                        + ("lower it or make it a Bed." if cover not in (None, "source") else "raise this line with Fine-tune."))
    # The original's words, when a layer plays over them.
    for a, b in lines:
        i0, i1 = round(a * rate), min(round(b * rate), n)
        over = [(eid, p) for eid, p in pieces.items() if p[0] < i1 and i0 < p[1]]
        mask = words_mask[i0:i1]
        if not over or not mask.any():
            continue
        others = np.zeros((i1 - i0, channels))
        for _, (p0, p1, piece) in over:
            lo, hi = max(p0, i0), min(p1, i1)
            others[lo - i0:hi - i0] += piece[lo - p0:hi - p0]
        ratio = L.loudness(out_base[i0:i1], rate, mask) - L.loudness(others, rate, mask)
        if ratio < settings.clear_db:
            loudest = max(over, key=lambda kv: L.loudness(kv[1][2], rate))[0]
            rep = reports.get(loudest)
            edit = next((x for x in layers if x.edit_id == loudest), None)
            if rep is not None and rep.flag is None and edit is not None:
                rep.flag = f"{_name(edit)} covers the words at {_clock(a)}; lower it or make it a Bed."
                rep.covered_by = "words"
    gains = {e.edit_id: L.gain(reports[e.edit_id].gain_db) for e, *_ in placed if e.edit_id in reports}
    return MixResult(out.astype(np.float32), voice_lufs, list(reports.values()), gains)


def _duck_curve(duck_db: np.ndarray, samples: int, rate: int, settings: MixSettings) -> np.ndarray:
    """A per-sample gain from per-frame dips (dB, <= 0), ramped like a bed's duck."""
    env = np.ones(samples)
    for depth in sorted(set(np.round(duck_db[duck_db < 0], 1))):
        active = np.isclose(np.round(duck_db, 1), depth)
        env = np.minimum(env, L.ramp_envelope(active, float(depth), samples, rate, settings.attack, settings.release, FRAME))
    return env


def _loudest_other(e, i0, i1, mask, pieces, layers, base, rate) -> tuple[str | None, str]:
    """What covers a voice: the loudest other layer in its span, or the original sound."""
    best, best_level = None, L.loudness(base[i0:i1], rate, mask)
    for eid, (p0, p1, piece) in pieces.items():
        if eid == e.edit_id or p1 <= i0 or i1 <= p0:
            continue
        lo, hi = max(p0, i0), min(p1, i1)
        seg = np.zeros((i1 - i0, piece.shape[1]))
        seg[lo - i0:hi - i0] = piece[lo - p0:hi - p0]
        level = L.loudness(seg, rate, mask)
        if level > best_level:
            best, best_level = eid, level
    if best is None:
        return "source", "The original sound"
    edit = next((x for x in layers if x.edit_id == best), None)
    return best, (_name(edit) if edit is not None else "Another line")
