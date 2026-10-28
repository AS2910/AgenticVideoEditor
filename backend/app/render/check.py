"""The check after every render (run 5 addendum 3, item 1).

Every rendered edit is listened to where it joins the video, and a line that
fails is not "In your video": its row says "Needs a fix" with the reason, in
plain words. The rules, each measured on the render against the original at
the same place:

- **overlap**: an added line's voice may not play over another line (the
  original's words still heard there, or another take). Two voices at once is
  a failure.
- **clipped**: a take cut short by its span (a later edit took part of it, or
  it was longer than its place), and a cut through the middle of an original
  word at a join.
- **jump**: the loudness step across a join (BS.1770 K-weighted, short-term:
  up to 3 s either side, ungated) more than JUMP_LU beyond the original's own
  step at that point. Music or ambience that dips or jumps under a replaced
  line shows up here.
- **click**: a one-sample spike at a join that stands far above the sound
  around it, and above whatever the original does there.
- **silence**: a pause longer than NEW_SILENCE that the original did not have.
- **words**: Whisper over the joined span (behind the `render.hear_check`
  flag; `hear` is None without it) must hear the new line's words, the first
  and last included. A heard sign-off ("Thanks for watching") or sound caption
  is Whisper's invention, screened out: the line is then not judged on words.

Pure apart from `hear`: arrays in, findings out. `api.main._render_now` runs it.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from app.media import loudness as L

RATE = 48000
JUMP_LU = 1.5            # a loudness step at a join beyond the original's, LU
SHORT_TERM = 3.0         # BS.1770 short-term window, seconds
MIN_WINDOW = 0.4         # a side shorter than this is too short to measure (one momentary block)
SILENT_LUFS = -60.0      # a window this quiet has no level to compare
NEW_SILENCE = 0.4        # seconds: a pause this long that was not there before
SILENCE_MARGIN = 0.1     # ... and longer than the original's longest there by this much
SILENCE_DB = 30.0        # quiet: this far under the loud part of the original around the line
OVERLAP = 0.05           # seconds of two voices at once that count
CUT = 0.05               # seconds of a take's sound lost before it counts as clipped
WORD_EDGE = 0.04         # a join this far inside a word on both sides cuts it
CLICK_WINDOW = 0.04      # seconds either side of a join searched for a click
CLICK_CONTEXT = 0.15     # seconds either side the click is judged against
CLICK_FLOOR = 0.05       # a step smaller than this (full scale 1.0) is never a click
CLICK_RATIO = 6.0        # a step this many times the 95th percentile step around it
HEAR_MARGIN = 0.15       # seconds either side of the line sent to Whisper
WORDS_KEPT = 0.6         # the share of the line's words that must be heard
FRAME = 0.01
SOUND_BELOW_PEAK_DB = 35.0

# (mono audio, rate, key) -> the words heard, None: not heard. The key names
# what was sent (the edit, its place, its take), the same across renders whose
# overall level differs, so a line heard once is not paid for again.
HearFn = Callable[[np.ndarray, int, str], "list[str] | None"]


@dataclass(frozen=True)
class Placed:
    """One rendered edit, as the check sees it."""
    edit_id: str
    kind: str                       # "replace" | "layer" | "remove"
    text: str
    src_start: float                # the source span it plays over
    src_end: float
    take: np.ndarray | None = None  # mono, the take as it plays from src_start (no level applied)
    lost_head: float = 0.0          # seconds of the take's sound cut off before its span
    lost_tail: float = 0.0          # ... and after it
    voice: bool = True              # a Bed or an Effect plays under words by design: no overlap, no words


@dataclass(frozen=True)
class Finding:
    edit_id: str
    rule: str                       # overlap | clipped | jump | click | silence | words
    reason: str                     # plain words for the row
    value: float | None = None


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    heard: dict[str, list[str]] = field(default_factory=dict)
    heard_seconds: float = 0.0      # what was sent to Whisper, for the ledger

    def needs_fix(self) -> dict[str, str]:
        """{edit id: the reason}, the first two findings per line."""
        out: dict[str, list[str]] = {}
        for f in self.findings:
            out.setdefault(f.edit_id, [])
            if len(out[f.edit_id]) < 2 and f.reason not in out[f.edit_id]:
                out[f.edit_id].append(f.reason)
        return {k: " ".join(v) for k, v in out.items()}

    def as_dict(self) -> dict:
        return {"needs_fix": self.needs_fix(),
                "findings": [{"edit_id": f.edit_id, "rule": f.rule, "reason": f.reason,
                              "value": None if f.value is None else round(f.value, 3)} for f in self.findings],
                "heard_seconds": round(self.heard_seconds, 2)}


# ── measuring ─────────────────────────────────────────────────────────────────

def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _frame_db(x: np.ndarray, rate: int) -> np.ndarray:
    frame = max(1, int(rate * FRAME))
    n = len(x) // frame
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt((x[: n * frame].astype(np.float64).reshape(n, frame) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def sounding(x: np.ndarray, rate: int = RATE, peak_db: float | None = None) -> tuple[float, float] | None:
    """(first, last) second of `x` (mono) that carries sound: within
    SOUND_BELOW_PEAK_DB of its loudest frame (or of `peak_db`); None for silence."""
    db = _frame_db(x, rate)
    if db.size == 0:
        return None
    top = float(db.max()) if peak_db is None else peak_db
    if top <= -90:
        return None
    on = np.flatnonzero(db > top - SOUND_BELOW_PEAK_DB)
    if on.size == 0:
        return None
    return on[0] * FRAME, (on[-1] + 1) * FRAME


def sound_seconds(x: np.ndarray, rate: int = RATE, peak_db: float | None = None) -> float:
    """How many seconds of `x` (mono) carry sound, against its own peak or `peak_db`."""
    db = _frame_db(x, rate)
    if db.size == 0:
        return 0.0
    top = float(db.max()) if peak_db is None else peak_db
    if top <= -90:
        return 0.0
    return float((db > top - SOUND_BELOW_PEAK_DB).sum()) * FRAME


def window_lufs(x: np.ndarray, a: float, b: float, rate: int = RATE) -> float:
    """Ungated K-weighted loudness of x[a:b] (seconds), with half a second of
    run-in so the filter has settled: BS.1770 short-term for a 3 s window."""
    i0, i1 = max(0, int(round(a * rate))), min(len(x), int(round(b * rate)))
    if i1 - i0 < int(0.1 * rate):
        return L.SILENCE
    pre = max(0, i0 - rate // 2)
    y = L.k_weighted(x[pre:i1], rate)[i0 - pre:]
    power = float((y ** 2).sum(axis=1).mean()) if y.ndim == 2 else float((y ** 2).mean())
    return -0.691 + 10 * np.log10(max(power, 1e-12))


def longest_quiet(x: np.ndarray, threshold_db: float, rate: int = RATE) -> float:
    """The longest run (seconds) of 10 ms frames of `x` (mono) under `threshold_db`."""
    db = _frame_db(x, rate)
    best = run = 0
    for quiet in db < threshold_db:
        run = run + 1 if quiet else 0
        best = max(best, run)
    return best * FRAME


def click_at(x: np.ndarray, t: float, rate: int = RATE) -> float:
    """How far the biggest sample step near `t` stands above the steps around
    it (a ratio), 0 when the step is too small to hear as a click."""
    mono = _mono(x)
    i = int(round(t * rate))
    w, c = int(CLICK_WINDOW * rate), int(CLICK_CONTEXT * rate)
    near = mono[max(0, i - w):i + w]
    around = mono[max(0, i - c):i + c]
    if near.size < 3 or around.size < 3:
        return 0.0
    step = float(np.max(np.abs(np.diff(near))))
    if step < CLICK_FLOOR:
        return 0.0
    typical = float(np.percentile(np.abs(np.diff(around)), 95))
    return step / max(typical, 1e-4)


# ── the words ─────────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    from app.media.fit import spoken
    return [t.strip("'") for t in _TOKEN.findall(spoken(text).lower().replace("%", " percent")) if t.strip("'")]


def _same(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def word_match(expected: Sequence[str], heard: Sequence[str]) -> tuple[int, bool, bool]:
    """(how many expected words were heard in order, first heard, last heard)."""
    n, m = len(expected), len(heard)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = best[i + 1][j + 1] + 1 if _same(expected[i], heard[j]) else max(best[i + 1][j], best[i][j + 1])
    first = any(_same(expected[0], h) for h in heard) if expected else True
    last = any(_same(expected[-1], h) for h in heard) if expected else True
    return best[0][0], first, last


def hear_key(p: Placed) -> str:
    """What a line's hearing depends on: the edit, where it plays, and its take."""
    import hashlib
    take = hashlib.sha256(np.round((p.take if p.take is not None else np.zeros(0)) * 32767).astype("<i2").tobytes()).hexdigest()[:16]
    return f"{p.edit_id}:{p.kind}:{p.src_start:.3f}:{p.src_end:.3f}:{take}"


def invented(words: Sequence[str]) -> bool:
    """Whisper's own inventions over a short span: a sign-off or a sound caption."""
    from app.adapters.openai_whisper import is_sign_off, is_sound_caption
    text = " ".join(words).strip()
    return bool(text) and (is_sign_off(text) or is_sound_caption(text))


# ── the check ─────────────────────────────────────────────────────────────────

def run(
    track: np.ndarray, original: np.ndarray, placed: Sequence[Placed],
    words: Sequence[tuple[str, float, float]] = (), out_time: Callable[[float], float] | None = None,
    hear: HearFn | None = None, rate: int = RATE,
) -> Report:
    """Check every placed edit in the render `track` against the `original`
    (both (samples, channels) at `rate`). `words` are the original's words
    (text, start, end) in source seconds; `out_time` maps a source moment to
    the render (the identity when the picture is not retimed)."""
    to_out = out_time or (lambda t: t)
    report = Report()
    covered = [(p.src_start, p.src_end) for p in placed if p.kind in ("replace", "remove")]

    def audible(a: float, b: float) -> bool:
        gone = sum(max(0.0, min(b, y) - max(a, x)) for x, y in covered)
        return gone < 0.5 * (b - a)

    heard_words = [(t, a, b) for t, a, b in words if b > a and audible(a, b)]
    voiced: dict[str, tuple[float, float]] = {}
    for p in placed:
        if p.take is not None and p.kind in ("replace", "layer") and p.voice:
            span = sounding(p.take, rate)
            if span is not None:
                start = to_out(p.src_start)
                voiced[p.edit_id] = (start + span[0], start + min(span[1], (p.src_end - p.src_start) if p.kind == "replace" else span[1]))

    mono_t, mono_o = _mono(track), _mono(original)
    starts = sorted({0.0, *(p.src_start for p in placed if p.kind != "layer"), *(p.src_end for p in placed if p.kind != "layer")})
    duration = len(original) / rate

    for p in placed:
        add = lambda rule, reason, value=None, p=p: report.findings.append(Finding(p.edit_id, rule, reason, value))  # noqa: E731
        a_out, b_out = to_out(p.src_start), to_out(p.src_end)

        # Two voices at once: an added voice over words still heard, or over another take.
        if p.kind == "layer" and p.voice and p.edit_id in voiced:
            s, e = voiced[p.edit_id]
            for text, wa, wb in heard_words:
                over = min(e, to_out(wb)) - max(s, to_out(wa))
                if over > OVERLAP:
                    add("overlap", f"Two voices at once: it plays over “{text}” at {_clock(to_out(wa))}.", over)
                    break
            for other, (os_, oe) in voiced.items():
                if other == p.edit_id:
                    continue
                over = min(e, oe) - max(s, os_)
                if over > OVERLAP:
                    add("overlap", f"Two voices at once: it plays over another new line at {_clock(max(s, os_))}.", over)
                    break

        # Clipped: the take cut short, or a join through an original word.
        if p.lost_tail > CUT:
            add("clipped", f"The end of the new line is cut off ({p.lost_tail:.1f} s of it is missing).", p.lost_tail)
        if p.lost_head > CUT:
            add("clipped", f"The start of the new line is cut off ({p.lost_head:.1f} s of it is missing).", p.lost_head)
        if p.kind in ("replace", "remove"):
            for text, wa, wb in words:
                for edge in (p.src_start, p.src_end):
                    if wa + WORD_EDGE < edge < wb - WORD_EDGE:
                        add("clipped", f"It cuts the word “{text}” in two at {_clock(to_out(edge))}.", edge)

        joins = [(a_out, p.src_start, "starts"), (b_out, p.src_end, "ends")]

        # A loudness step at a join beyond the original's own (replaced and removed lines).
        if p.kind in ("replace", "remove"):
            prev = max((t for t in starts if t < p.src_start - 1e-6), default=0.0)
            nxt = min((t for t in starts if t > p.src_end + 1e-6), default=duration)
            span = p.src_end - p.src_start
            sides = [(p.src_start, min(SHORT_TERM, p.src_start - prev), min(SHORT_TERM, span), "starts"),
                     (p.src_end, min(SHORT_TERM, span), min(SHORT_TERM, nxt - p.src_end), "ends")]
            for t, before, after, word in sides:
                if before < MIN_WINDOW or after < MIN_WINDOW:
                    continue
                levels = [window_lufs(track, to_out(t - before), to_out(t), rate), window_lufs(track, to_out(t), to_out(t + after), rate),
                          window_lufs(original, t - before, t, rate), window_lufs(original, t, t + after, rate)]
                if min(levels) <= SILENT_LUFS:
                    continue
                step = abs((levels[1] - levels[0]) - (levels[3] - levels[2]))
                if step > JUMP_LU:
                    add("jump", f"The sound jumps {step:.1f} LU where the new line {word}.", step)
                    break

        # A click at a join.
        for t_out, t_src, word in joins:
            ours = click_at(track, t_out, rate)
            theirs = click_at(original, t_src, rate)
            if ours > CLICK_RATIO and ours > 2 * max(theirs, 1.0):
                add("click", f"There is a click where the new line {word}.", ours)
                break

        # A pause that was not there before (a replaced line: added ones only add sound).
        if p.kind == "replace":
            o0, o1 = max(0, int((p.src_start - 0.5) * rate)), int((p.src_end + 0.5) * rate)
            r0, r1 = max(0, int((a_out - 0.5) * rate)), int((b_out + 0.5) * rate)
            loud = np.percentile(_frame_db(mono_o[o0:o1], rate), 95) if o1 - o0 > rate // 10 else -120.0
            if loud > -90:
                threshold = loud - SILENCE_DB
                ours, theirs = longest_quiet(mono_t[r0:r1], threshold, rate), longest_quiet(mono_o[o0:o1], threshold, rate)
                if ours > NEW_SILENCE and ours > theirs + SILENCE_MARGIN:
                    add("silence", f"There is a {ours:.1f} s silence that was not there before.", ours)

        # The words, heard: Whisper over the joined span.
        if hear is not None and p.kind in ("replace", "layer") and p.voice and tokens(p.text):
            end_out = b_out if p.kind == "replace" else (voiced.get(p.edit_id, (a_out, b_out))[1])
            i0 = max(0, int((a_out - HEAR_MARGIN) * rate))
            i1 = min(len(mono_t), int((end_out + HEAR_MARGIN) * rate))
            if i1 - i0 > rate // 10:
                heard = hear(mono_t[i0:i1], rate, hear_key(p))
                report.heard_seconds += (i1 - i0) / rate
                if heard is not None and not invented(heard):
                    report.heard[p.edit_id] = list(heard)
                    expected, got = tokens(p.text), tokens(" ".join(heard))
                    matched, first, last = word_match(expected, got)
                    if not got:
                        add("words", "No words were heard where the new line plays.", 0.0)
                    elif not last:
                        add("words", f"The last word, “{expected[-1]}”, is not heard: it may be cut off.", matched / len(expected))
                    elif not first:
                        add("words", f"The first word, “{expected[0]}”, is not heard: it may be cut off.", matched / len(expected))
                    elif matched < WORDS_KEPT * len(expected):
                        add("words", f"Heard “{' '.join(heard)}”, not the new line.", matched / len(expected))
    return report
