"""The arrangement of a video's spoken lines (2026-10-19).

The transcript's order is the playback order. Each line starts where the
previous one ends plus its own gap: the pause that came before it in the
original, so the pacing is kept. A pinned line starts at its pinned time;
the lines around it flow, and a flowing line that would run into a pinned
one is pushed to after it. With nothing changed the arrangement is the
original timing, exactly.

Pure: lines in, placements out. The front end runs the same function (a
TypeScript port, `frontend/src/transcript/arrange.ts`) for the live preview
while a line is dragged; both are tested against `tests/fixtures/arrange-cases.json`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_MIN_GAP = 0.15        # Tighten gaps: every pause shrinks to at most this (seconds)
EASE_LIMIT_S = 1.5            # the picture may hold its last frame this long, no longer
EPS = 1e-6


@dataclass(frozen=True)
class LineSpec:
    key: str                  # "L<n>": the n-th spoken line of the transcript, 0-based
    orig_start: float
    orig_end: float
    length: float             # how long it plays: its own span, or its fitted take's
    gap: float                # the pause before it in the original (the lead-in for the first)


@dataclass(frozen=True)
class Placed:
    key: str
    start: float
    end: float
    pinned: bool = False
    pushed_after: float | None = None   # the pinned line's start it was pushed after, if it was
    moved: bool = False


@dataclass(frozen=True)
class Arrangement:
    order: tuple[str, ...] = ()
    pins: dict = field(default_factory=dict)       # key -> start (seconds)
    min_gap: float | None = None                    # set by Tighten gaps
    end: str | None = None                          # how a run past the end is handled: "hold" | "trim"

    @staticmethod
    def from_dict(d: dict | None) -> "Arrangement":
        d = d or {}
        return Arrangement(order=tuple(d.get("order") or ()), pins={str(k): float(v) for k, v in (d.get("pins") or {}).items()},
                           min_gap=d.get("min_gap"), end=d.get("end"))

    def as_dict(self) -> dict:
        return {"order": list(self.order), "pins": dict(self.pins), "min_gap": self.min_gap, "end": self.end}

    def is_default(self, keys: list[str]) -> bool:
        return (not self.order or list(self.order) == keys) and not self.pins and self.min_gap is None


def specs(statements, lengths: dict[str, float] | None = None) -> list[LineSpec]:
    """The spoken lines as the arrangement sees them, in their original order."""
    out: list[LineSpec] = []
    prev_end = 0.0
    for i, st in enumerate(statements):
        key = f"L{i}"
        length = (lengths or {}).get(key, st.end - st.start)
        out.append(LineSpec(key, round(st.start, 3), round(st.end, 3), round(max(0.0, length), 3), round(max(0.0, st.start - prev_end), 3)))
        prev_end = st.end
    return out


def ordered(lines: list[LineSpec], arrangement: Arrangement) -> list[LineSpec]:
    """The lines in the arrangement's order; lines it does not name keep their place after the named ones."""
    by_key = {ln.key: ln for ln in lines}
    named = [by_key[k] for k in arrangement.order if k in by_key]
    seen = {ln.key for ln in named}
    return named + [ln for ln in lines if ln.key not in seen]


def _gap(lines: list[LineSpec], seq: list[LineSpec], i: int, min_gap: float | None) -> float:
    """The pause before the i-th line played. The first keeps the clip's
    lead-in, whichever line it is; the line that was first, played later,
    takes the pause that followed it, so it does not carry the lead-in along."""
    if i == 0:
        return lines[0].gap if lines else 0.0
    ln = seq[i]
    gap = (lines[1].gap if len(lines) > 1 else 0.0) if lines and ln.key == lines[0].key else ln.gap
    return min(gap, min_gap) if min_gap is not None else gap


def place(lines: list[LineSpec], arrangement: Arrangement) -> list[Placed]:
    """Where each line plays, sorted by when it starts (the transcript's order)."""
    seq = ordered(lines, arrangement)
    gap_of = {ln.key: _gap(lines, seq, i, arrangement.min_gap) for i, ln in enumerate(seq)}
    pinned = {ln.key: (round(arrangement.pins[ln.key], 3), round(arrangement.pins[ln.key] + ln.length, 3))
              for ln in seq if ln.key in arrangement.pins}
    out: list[Placed] = []
    cursor = 0.0
    for ln in seq:
        if ln.key in pinned:
            start, end = pinned[ln.key]
            out.append(Placed(ln.key, start, end, pinned=True, moved=abs(start - ln.orig_start) > 0.005))
            cursor = end
            continue
        gap = gap_of[ln.key]
        start = round(cursor + gap, 3)
        pushed = None
        # A flowing line never runs into a pinned one: it waits until that line has played.
        changed = True
        while changed:
            changed = False
            for key, (ps, pe) in sorted(pinned.items(), key=lambda kv: kv[1][0]):
                if start < pe - EPS and start + ln.length > ps + EPS:
                    start, pushed, changed = round(pe + gap, 3), ps, True
        end = round(start + ln.length, 3)
        out.append(Placed(ln.key, start, end, pushed_after=pushed, moved=abs(start - ln.orig_start) > 0.005))
        cursor = end
    # Playback order: the transcript shows the lines in the order they are heard.
    return sorted(out, key=lambda p: (p.start, p.key))


def overrun(placed: list[Placed], duration: float) -> float:
    """How far the arrangement runs past the end of the clip (0 when it fits)."""
    last = max((p.end for p in placed), default=0.0)
    return round(max(0.0, last - duration), 3)


def pin_conflict(lines: list[LineSpec], pins: dict) -> str | None:
    """Two pinned lines that would play at once: the sentence that says so, else None."""
    length = {ln.key: ln.length for ln in lines}
    spans = sorted((float(s), float(s) + length.get(k, 0.0), k) for k, s in pins.items() if k in length)
    for (a0, a1, ka), (b0, b1, kb) in zip(spans, spans[1:]):
        if b0 < a1 - EPS:
            return f"Those two pinned lines would play at once ({ka} until {a1:.1f} s, {kb} from {b0:.1f} s). Unpin one or move it."
    return None
