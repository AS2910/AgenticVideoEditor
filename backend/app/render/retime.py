"""Picture that flexes (Phase 16): the output as pieces of the source.

The export used to be the source's own frames everywhere, with one exception —
an added line froze the frame while it played. Now the picture gives a little:

- A **flex** piece is a replaced line whose picture runs up to `MAX_FLEX`
  slower or faster, so the take fits at natural speech (`EditPlan.flex`).
- A **living** piece makes room for an added line by stretching the pause
  after it — up to `max_living`, never across a cut — and, when the pause is
  too short to hold the whole line even so, by playing the stretched pause
  forwards and back (a ping-pong) until the line is done. When there is no
  pause at all the tail of the line itself is the window. The room's own
  sound sits under the new line.
- A **hold** is the old frozen frame, kept only for a window too short to
  stretch (under `MIN_WINDOW`), and said so.
- A **copy** is the source as shot.

Within a stretched window the extra time goes where the picture moves least
(`media.motion`), each chunk within the limit. Every piece's length is a whole
number of frames, so the audio assembled from the same pieces lines up exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Sequence

from app.domain.models import ApprovedEdit, Selection, Transcript
from app.domain.transcript import room_after
from app.media.motion import CHUNK, chunk_count
from app.media.shots import shot_around
from app.render.renderer import RenderInsert

MIN_WINDOW = 0.12     # a window shorter than this has nothing to stretch: hold, and say so
TAIL = 0.4            # the fallback window: the end of the line itself, before the insert point
MotionFn = Callable[[float, float], Sequence[float]]   # (start, end) -> motion per chunk


@dataclass(frozen=True)
class Chunk:
    start: float
    end: float
    factor: float     # this stretch of the source runs `factor` times its length


@dataclass(frozen=True)
class Piece:
    start: float                     # the source window; start == end for a hold
    end: float
    out: float                       # output seconds
    kind: str                        # copy | flex | living | hold
    chunks: tuple[Chunk, ...] = ()   # flex / living: how one pass of the window is stretched
    loops: int = 1                   # living: passes of the stretched window (forward, back, forward…)
    edit: ApprovedEdit | None = None # flex: the line's edit; living / hold: the added line's
    line_first: bool = True          # living: the added line plays before the window's own sound

    @property
    def factor(self) -> float | None:
        if self.kind == "copy" or self.end <= self.start:
            return None
        return round(self.out / (self.end - self.start), 4)

    @property
    def held(self) -> float:
        return self.out if self.kind == "hold" else 0.0


def allocate(start: float, end: float, extra: float, motion: Sequence[float], max_factor: float,
             chunk: float = CHUNK) -> tuple[Chunk, ...]:
    """Share `extra` seconds (negative to squeeze) across the window's chunks,
    in inverse proportion to how much each moves, no chunk past `max_factor`
    (or under 1/max_factor). What the chunks cannot take is left out."""
    length = end - start
    n = max(1, len(motion)) if motion else chunk_count(length, chunk)
    bounds = [(start + length * i / n, start + length * (i + 1) / n) for i in range(n)]
    lengths = [b - a for a, b in bounds]
    weights = [1.0 / (float(m) + 1e-3) for m in (motion or [0.0] * n)]
    caps = [ln * (max_factor - 1.0) if extra >= 0 else ln * (1.0 - 1.0 / max_factor) for ln in lengths]
    added = [0.0] * n
    remaining = abs(extra)
    for _ in range(6):
        open_ = [i for i in range(n) if added[i] < caps[i] - 1e-9]
        if remaining <= 1e-9 or not open_:
            break
        total = sum(weights[i] for i in open_)
        for i in open_:
            share = min(remaining * weights[i] / total, caps[i] - added[i])
            added[i] += share
        remaining = abs(extra) - sum(added)
    sign = 1.0 if extra >= 0 else -1.0
    return tuple(Chunk(a, b, (ln + sign * add) / ln) for (a, b), ln, add in zip(bounds, lengths, added))


def _frames(seconds: float, fps: float) -> int:
    return int(round(seconds * fps))


def flex_pieces(edits: Sequence[ApprovedEdit], motion: MotionFn | None = None,
                max_flex: float = 1.12) -> list[Piece]:
    """One flex piece per live replaced edit whose plan carries a factor."""
    pieces = []
    for e in edits:
        if e.reverted or e.plan.mix != "replace" or not e.plan.flex or abs(e.plan.flex - 1) < 1e-6:
            continue
        a, b = e.plan.selection.start, e.plan.selection.end
        if b <= a:
            continue
        flex = e.plan.flex
        extra = (b - a) * (flex - 1.0)
        # Low-motion chunks take more of the stretch, up to twice the mean, so the whole stays at `flex`.
        cap = 1.0 + 2.0 * abs(flex - 1.0)
        m = motion(a, b) if motion else []
        chunks = allocate(a, b, extra, m, max(cap, max_flex if flex > 1 else 1.0 / (1.0 / max_flex)))
        pieces.append(Piece(a, b, e.audio.duration, "flex", chunks, 1, e))
    return pieces


def living_pieces(
    inserts: Sequence[RenderInsert], transcript: Transcript | None, duration: float,
    cuts: Sequence[float] = (), motion: MotionFn | None = None, max_living: float = 1.6,
    taken: Sequence[tuple[float, float]] = (),
) -> list[Piece]:
    """A living piece per added line, or a hold when there is no window to stretch."""
    pieces: list[Piece] = []
    busy = list(taken)
    for ins in sorted(inserts, key=lambda i: i.at):
        at = min(max(ins.at, 0.0), duration)
        d = ins.duration
        _, shot_end = shot_around(at, cuts, duration)
        room = room_after(transcript, Selection(at, at), duration) if transcript else duration - at
        w_end = min(at + room, shot_end, duration)
        window, line_first = (at, w_end), True
        if w_end - at < MIN_WINDOW:
            shot_start, _ = shot_around(max(0.0, at - 1e-3), cuts, duration)
            w_start = max(shot_start, at - TAIL, 0.0)
            window, line_first = (w_start, at), False
        a, b = window
        free = b - a >= MIN_WINDOW and not any(a < t1 and t0 < b for t0, t1 in busy)
        if not free:
            pieces.append(Piece(at, at, d, "hold", (), 1, ins.edit))
            busy.append((at, at))
            continue
        length = b - a
        one_pass = length * max_living
        if length + d <= one_pass + 1e-9:
            chunks = allocate(a, b, d, motion(a, b) if motion else [], max_living)
            loops = 1
        else:
            chunks = allocate(a, b, length * (max_living - 1.0), motion(a, b) if motion else [], max_living)
            loops = int(math.ceil((length + d) / one_pass))
        pieces.append(Piece(a, b, length + d, "living", chunks, loops, ins.edit, line_first))
        busy.append((a, b))
    return pieces


def plain_holds(inserts: Sequence[RenderInsert], duration: float) -> list[Piece]:
    """The old behaviour: every added line freezes the frame at its point."""
    return [Piece(min(max(i.at, 0.0), duration), min(max(i.at, 0.0), duration), i.duration, "hold", (), 1, i.edit)
            for i in sorted(inserts, key=lambda i: i.at)]


def tile(duration: float, special: Sequence[Piece], fps: float) -> list[Piece]:
    """Every piece of the output in order: the special ones, copies between
    them, every length a whole number of frames at `fps`."""
    ordered = sorted(special, key=lambda p: (p.start, p.end))
    for x, y in zip(ordered, ordered[1:]):
        if y.start < x.end - 1e-9:
            raise ValueError(f"pieces overlap: {x.kind} {x.start:.3f}-{x.end:.3f} and {y.kind} {y.start:.3f}-{y.end:.3f}")
    out: list[Piece] = []
    cursor = 0.0
    for p in ordered:
        if p.start > cursor + 1e-9:
            out.append(Piece(cursor, p.start, p.start - cursor, "copy"))
        out.append(p)
        cursor = max(cursor, p.end)
    if duration > cursor + 1e-9:
        out.append(Piece(cursor, duration, duration - cursor, "copy"))
    # Whole frames: boundaries and outputs land on the frame grid.
    snapped: list[Piece] = []
    for p in out:
        a, b = _frames(p.start, fps) / fps, _frames(p.end, fps) / fps
        if p.kind == "copy":
            length = b - a
            if length <= 1e-9:
                continue
            snapped.append(replace(p, start=a, end=b, out=length))
        else:
            n = _frames(p.out, fps)
            if n <= 0:
                continue
            snapped.append(replace(p, start=a, end=b if p.kind != "hold" else a, out=n / fps))
    return snapped


@dataclass(frozen=True)
class Placed:
    piece: Piece
    out_start: float
    out_end: float


def place(pieces: Sequence[Piece]) -> list[Placed]:
    """Each piece with where it falls in the output."""
    placed, t = [], 0.0
    for p in pieces:
        placed.append(Placed(p, round(t, 6), round(t + p.out, 6)))
        t += p.out
    return placed


def manifest(pieces: Sequence[Piece]) -> list[dict]:
    return [
        {"start": round(x.piece.start, 3), "end": round(x.piece.end, 3), "out_start": round(x.out_start, 3),
         "out_end": round(x.out_end, 3), "kind": x.piece.kind, "factor": x.piece.factor}
        for x in place(pieces)
    ]


def render_time(t: float, pieces: Sequence[Piece]) -> float:
    """Where a moment of the source falls in the output (a held moment: after its hold)."""
    for x in place(pieces):
        p = x.piece
        if p.kind == "hold":
            continue
        if p.start <= t < p.end or (t == p.end and x is place(pieces)[-1]):
            return x.out_start + (t - p.start) / (p.end - p.start) * p.out if p.end > p.start else x.out_start
    return t


def held_seconds(pieces: Sequence[Piece]) -> float:
    return round(sum(p.held for p in pieces), 3)
