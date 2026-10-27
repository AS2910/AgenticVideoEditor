"""The breakage table of a messy run, as Markdown: variant x transcription,
voice matching, timing (and the bed under a replaced line).

Rules (what "breaks" means):
- transcription: word recall under 0.90, or a line lost. Extra words are
  reported, not counted, on the crosstalk variants (the second voice really
  speaks).
- timing: a line's replaced span moves more than 0.20 s from where the clean
  clip's own transcript puts it, or the line is gone. Measured against the
  clean run, so Whisper's habits that are there on clean audio too (the first
  word pinned to 0.0 s) are not blamed on the mess.
- voice matching: the speaker's own clean line (a perfect take) for line 4
  fails the continuity check against the messy context.
"""
from __future__ import annotations

import json
from pathlib import Path

EDGE_S = 0.20
VOICE_LINE = 3


def _load(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text()) if path else None


def _edges(row: dict) -> dict[int, tuple[float, float] | None]:
    out = {}
    for t in (row.get("transcription") or {}).get("timing", []):
        out[t["line"]] = (t["start_err"], t["end_err"]) if t.get("found") else None
    return out


def judge(run: dict) -> dict[str, dict]:
    rows = {r["variant"]: r for r in run["rows"]}
    clean = _edges(rows["clean"]) if "clean" in rows else {}
    out = {}
    for name, r in rows.items():
        t = r.get("transcription") or {}
        cell: dict = {}
        if "recall" not in t:
            cell["transcription"] = ("n/a", t.get("error", "not run"))
            cell["timing"] = ("n/a", "")
        else:
            why = []
            if t["recall"] < 0.90:
                why.append(f"recall {t['recall']:.2f}")
            if t["lines_lost"]:
                why.append(f"{t['lines_lost']} of 5 lines lost")
            extra = f", {t['invented']} extra words" if t["invented"] > 1 else ""
            cell["transcription"] = ("BREAK" if why else "ok", ", ".join(why) or f"recall {t['recall']:.2f}{extra}")
            worst, lost = 0.0, 0
            for line, e in _edges(r).items():
                base = clean.get(line)
                if e is None:
                    lost += 1
                    continue
                if base is not None:
                    worst = max(worst, abs(e[0] - base[0]), abs(e[1] - base[1]))
            tw = []
            if lost:
                tw.append(f"{lost} lines have no span")
            if worst > EDGE_S:
                tw.append(f"an edge moves {worst:.2f} s")
            cell["timing"] = ("BREAK" if tw else "ok", ", ".join(tw) or f"worst edge {worst:.2f} s")
        own = next((v for v in r.get("voice", []) if v["line"] == VOICE_LINE and v["take"] == "own"), None)
        if own is None:
            cell["voice"] = ("n/a", "")
        else:
            detail = f"match {own['voice_match']}, mix {own['integration']}"
            if own["passed"]:
                cell["voice"] = ("ok", detail)
            else:
                cell["voice"] = ("BREAK", (own["warnings"] or [detail])[0])
        bk = r.get("bed_kept")
        if bk:
            w = (bk.get("without_stems") or {}).get("bed")
            s = (bk.get("with_stems") or {}).get("bed")
            cell["bed"] = f"{w if w is not None else '-'} / {s if s is not None else 'dropped'}"
        out[name] = cell
    return out


def main(result: str, before: str | None = None) -> str:
    run, prev = _load(result), _load(before)
    now = judge(run)
    was = judge(prev) if prev else {}
    lines = ["| Variant | Transcription | Voice matching | Timing | Bed under the new line (no stems / stems) |",
             "| --- | --- | --- | --- | --- |"]

    def cell(name: str, key: str) -> str:
        verdict, detail = now[name][key]
        if name in was and was[name][key][0] != verdict:
            return f"{was[name][key][0]} -> **{verdict}** ({detail})"
        return f"{verdict} ({detail})" if detail else verdict

    for name in now:
        lines.append(f"| {name} | {cell(name, 'transcription')} | {cell(name, 'voice')} | {cell(name, 'timing')} | "
                     f"{now[name].get('bed', '')} |")
    breaks = {k: sum(1 for c in now.values() if c[k][0] == "BREAK") for k in ("transcription", "voice", "timing")}
    lines.append("")
    lines.append(f"Breaks: transcription {breaks['transcription']}, voice matching {breaks['voice']}, "
                 f"timing {breaks['timing']} (of {len(now)} rows, the clean control included). "
                 f"Spend this run: ${run['spend']['usd']:.4f}.")
    return "\n".join(lines)
