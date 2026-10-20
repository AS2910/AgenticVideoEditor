"""Writing to length, and lines that run long (2026-10-20, p61).

On the boxing clip every commentary line ended "too long for its gap": the
lines were written without their time budget, voiced before anyone checked,
and never tried shorter. Here is what fixes that, as plain functions the
tools and the loop call:

- every voice's speaking rate, measured from its own takes (the default
  until it has some), and a log of estimate against actual for each take;
- the placement windows of a clip and the syllables each one holds, for a
  set of lines planned together;
- the pre-flight estimate that refuses a line before anything is paid;
- the end of a turn: a line that failed for length is tried shorter in the
  same turn, or the user is asked once about all of them together.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from app.media import fit

RATES_KEY = "voice_rates"        # meta: {voice_id: {"samples": [[syllables, seconds], ...]}}
LOG_KEY = "fit_log"              # meta: [{at, video, item, voice_id, text, estimate_s, actual_s, window_s, speed, outcome}]
MAX_SAMPLES = 20                 # the newest takes a voice's rate is read from
MAX_LOG = 300
TOO_LONG = "too_long"


# ── a voice's own rate ────────────────────────────────────────────────────────

def _meta(repo: Any, key: str, default: Any) -> Any:
    get = getattr(repo, "get_meta", None)
    if get is None:
        return default
    try:
        return json.loads(get(key) or "null") or default
    except (TypeError, ValueError):
        return default


def voice_rate(repo: Any, voice_id: str | None) -> tuple[float, int]:
    """(syllables a second at speed 1, how many takes it was measured from).
    A voice with no measured takes speaks at the default rate."""
    samples = ((_meta(repo, RATES_KEY, {}).get(voice_id or "") or {}).get("samples") or [])
    seconds = sum(float(s[1]) for s in samples)
    if not samples or seconds <= 0:
        return fit.DEFAULT_VOICE_RATE, 0
    rate = sum(float(s[0]) for s in samples) / seconds
    return round(min(8.0, max(2.0, rate)), 2), len(samples)


def rate_words(name: str, rate: float, takes: int) -> str:
    if takes:
        return f"{name} speaks about {rate:.1f} syllables a second (measured over {takes} {'take' if takes == 1 else 'takes'})"
    return f"{name} speaks about {rate:.1f} syllables a second (the default until {name} has takes)"


def learn(repo: Any, voice_id: str, text: str, seconds: float, speed: float, *, estimate: float | None,
          window: float, video: str, item: str, outcome: str, at: str) -> None:
    """One measured take: its rate joins the voice's, and the estimate made
    before it is logged against what it measured, so the estimate improves."""
    setter = getattr(repo, "set_meta", None)
    if setter is None or seconds <= 0:
        return
    sample = fit.rate_sample(text, seconds, speed)
    if sample is not None and voice_id:
        rates = _meta(repo, RATES_KEY, {})
        entry = rates.get(voice_id) or {}
        entry["samples"] = [*(entry.get("samples") or []), list(sample)][-MAX_SAMPLES:]
        rates[voice_id] = entry
        setter(RATES_KEY, json.dumps(rates))
    log = _meta(repo, LOG_KEY, [])
    log.append({"at": at, "video": video, "item": item, "voice_id": voice_id, "text": text,
                "estimate_s": None if estimate is None else round(estimate, 2), "actual_s": round(seconds, 2),
                "window_s": round(window, 2), "speed": round(speed, 2), "outcome": outcome})
    setter(LOG_KEY, json.dumps(log[-MAX_LOG:]))


# ── the pre-flight check ──────────────────────────────────────────────────────

def preflight(text: str, window: float, rate: float, speed: float = 1.0, ease: float = 1.0) -> dict | None:
    """None when the line should fit its window; else what it would take,
    {estimate, window, syllables, budget}. A line may run up to
    PREFLIGHT_OVER past its window (and the picture's ease, when allowed):
    the fit ladder covers that much."""
    estimate = fit.estimate_seconds(text, rate, speed)
    if estimate <= window * (1 + fit.PREFLIGHT_OVER) * max(1.0, ease) + 1e-9:
        return None
    return {"estimate": estimate, "window": window, "syllables": fit.syllables(fit.spoken(text)),
            "budget": fit.syllables_for(window, rate, text, speed)}


def refusal_text(check: dict) -> str:
    return (f"Too long: about {check['estimate']:.1f} s for a {check['window']:.1f} s window; rewrite to about "
            f"{check['budget']} syllables (it has {check['syllables']} now) and call again. Nothing was voiced or paid.")


# ── beats and windows ─────────────────────────────────────────────────────────

def beats(settings: dict) -> list[tuple[float, str]]:
    """The clip's beats as (time, what happens), the user's corrections
    applied; cuts left out. From the understanding, else the first look."""
    understood = settings.get("understanding")
    if understood:
        from app.understanding import view
        found = [(float(b["at"]), str(b.get("label") or "")) for b in view(understood).get("beats", []) if b.get("kind") != "cut"]
        if found:
            return sorted(found)
    sight = settings.get("sight") or {}
    return sorted((float(b["at"]), str(b.get("note") or "")) for b in sight.get("beats") or [] if "at" in b)


def windows(duration: float, marks: Sequence[tuple[float, str]]) -> list[tuple[float, float, str]]:
    """Where lines can go on a clip with no speech: from each beat to the
    next (the opening before the first beat when it is a second or more)."""
    times = [(t, label) for t, label in marks if 0.0 <= t < duration - 0.3]
    if not times:
        return [(0.0, duration, "")]
    out = []
    if times[0][0] >= 1.0:
        out.append((0.0, times[0][0], "the opening"))
    for i, (t, label) in enumerate(times):
        end = times[i + 1][0] if i + 1 < len(times) else duration
        out.append((t, end, label))
    return out


def plan(lines: Sequence[dict], duration: float, rate: float, speed: float = 1.0, commentary: bool = False) -> dict:
    """Several added lines planned together. Each line's window ends where
    the next line starts (less a breath, LINE_GAP) or at its own end; the
    budget is what that window holds at the voice's rate. For commentary the
    talk stays under COMMENTARY_SHARE of the clip, so the lines breathe."""
    ordered = sorted((dict(ln) for ln in lines), key=lambda ln: float(ln.get("start") or 0.0))
    spans = []
    for i, ln in enumerate(ordered):
        start = max(0.0, float(ln.get("start") or 0.0))
        nxt = float(ordered[i + 1].get("start") or 0.0) if i + 1 < len(ordered) else None
        given = float(ln.get("end") or -1)
        end = given if given > start else (nxt if nxt is not None else duration)
        if nxt is not None:
            end = min(end, nxt - fit.LINE_GAP)
        spans.append((start, min(end, duration)))
    # Commentary breathes: the windows together hold at most COMMENTARY_SHARE
    # of the clip, so each budget is that share of its window when they would not.
    limit = round(duration * fit.COMMENTARY_SHARE, 2)
    total = sum(max(0.0, e - s) for s, e in spans)
    share = min(1.0, limit / total) if commentary and total > 0 else 1.0
    out = []
    for (start, end), ln in zip(spans, ordered):
        window = round(max(0.0, end - start), 2)
        text = str(ln.get("text") or "")
        estimate = fit.estimate_seconds(text, rate, speed) if text.strip() else None
        out.append({"start": round(start, 2), "end": round(end, 2), "window": window, "text": text,
                    "estimate": estimate, "syllables": fit.syllables(fit.spoken(text)) if text.strip() else 0,
                    "budget": fit.syllables_for(window * share, rate, text, speed) if window > 0 else 0,
                    "fits": estimate is None or estimate <= window + 1e-9})
    talk = sum(min(r["estimate"] if r["estimate"] is not None else r["window"] * share, r["window"]) for r in out)
    return {"lines": out, "talk": round(talk, 2), "share": round(talk / duration, 3) if duration > 0 else 0.0,
            "limit": limit, "over": bool(commentary and talk > limit + 1e-9), "breathing": share < 1.0}


# ── a line that ran long ──────────────────────────────────────────────────────

def shorter_budget(syllables: int, needs: float, has: float) -> int:
    """The syllables a line that measured `needs` seconds for `syllables`
    should be rewritten to, to fit `has` at the same pace."""
    if needs <= 0:
        return max(1, syllables)
    return max(1, int(syllables * has / needs))


def pending(failed: dict, retried: set) -> list[dict]:
    """The lines that failed for length this turn and were not tried shorter."""
    return [info for item_id, info in failed.items() if item_id not in retried]


def group_question(lines: Sequence[dict]) -> tuple[str, tuple[str, ...], tuple[str, ...], float]:
    """One question about every line that needs a shorter version: the
    sentence, the options, the line under each, and what it would cost."""
    n = len(lines)
    usd = round(sum(float(i.get("cost_usd") or 0.0) for i in lines), 2)
    what = "1 line needs a shorter version" if n == 1 else f"{n} lines need shorter versions"
    question = f"{what}, about ${usd:.2f}. Go ahead?"
    details = (f"Rewrite {'it' if n == 1 else 'each'} to fit {'its gap' if n == 1 else 'their gaps'} and voice "
               f"{'it' if n == 1 else 'each'} once.",
               "They stay as they are; shorten, ease or discard them from their rows.")
    return question, ("Go ahead", "Leave them for now"), details, usd


def nudge(lines: Sequence[dict]) -> str:
    """What the editor tells Voltage when it would end the turn with lines
    that ran long and were not tried shorter."""
    parts = "; ".join(f"{i['item_id']} (“{i['text']}”: about {i['budget']} syllables for {i['has']:.1f} s)" for i in lines)
    return ("Not finished: these lines were too long for their gaps and have not been tried shorter: " + parts
            + ". Rewrite each to its syllables and voice it again once now, with its item_id. Then close the turn.")
