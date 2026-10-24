"""The scores: WER, SIM-o, UTMOS, duration error, plan quality, and cost.

WER is a tiny word-level edit distance over normalised words (no jiwer).
SIM-o and UTMOS come from `app.continuity.similarity` and run locally.
Speech to text is the only paid scorer: each take is heard once, and what it
costs is added to the run's scoring spend, apart from the app's own ledger.
Whisper (OpenAI) when its key works, else ElevenLabs Scribe, which plays the
same part (2026-10-24: the OpenAI key had expired).
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Sequence

import httpx

WHISPER_USD_PER_MINUTE = 0.006
SCRIBE_USD_PER_MINUTE = 0.40 / 60      # the API's list price per hour of audio, at its highest
_NUMBERS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
            "eight": "8", "nine": "9", "ten": "10", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50"}


def words(text: str) -> list[str]:
    """Lower case, % said as a word, punctuation (any script) dropped."""
    text = unicodedata.normalize("NFC", (text or "").lower().replace("%", " percent "))
    out = []
    for token in text.split():
        kept = "".join(ch for ch in token if not unicodedata.category(ch).startswith(("P", "S")))
        if kept:
            out.append(_NUMBERS.get(kept, kept))
    return out


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate of `hypothesis` against `reference` (0 is exact)."""
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def duration_of(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip() or 0)


def transcribe(path: Path, keys: dict, language: str | None = None) -> tuple[str, float]:
    """The words heard in one take, and what hearing them cost."""
    if keys.get("openai"):
        return _whisper(path, keys["openai"], language)
    return _scribe(path, keys["elevenlabs"], language)


def _scribe(path: Path, api_key: str, language: str | None) -> tuple[str, float]:
    data = {"model_id": "scribe_v1", "tag_audio_events": "false"}
    if language:
        data["language_code"] = language
    with path.open("rb") as handle:
        r = httpx.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": api_key},
                       files={"file": (path.name, handle, "audio/wav")}, data=data, timeout=120.0)
    r.raise_for_status()
    return r.json().get("text", ""), duration_of(path) / 60 * SCRIBE_USD_PER_MINUTE


def _whisper(path: Path, api_key: str, language: str | None) -> tuple[str, float]:
    data = {"model": "whisper-1", "response_format": "json"}
    if language:
        data["language"] = language
    with path.open("rb") as handle:
        r = httpx.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {api_key}"},
                       files={"file": (path.name, handle, "audio/wav")}, data=data, timeout=120.0)
    r.raise_for_status()
    return r.json().get("text", ""), duration_of(path) / 60 * WHISPER_USD_PER_MINUTE


def segment(src: Path, start: float, end: float, dest: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
                    "-ac", "1", "-ar", "16000", str(dest)], check=True)
    return dest


def voice_scores(take: Path, reference: Path | None) -> dict:
    """SIM-o against the speaker the take replaces (None for an added line), and UTMOS."""
    from app.continuity import similarity
    return {"sim_o": similarity.speaker_similarity(reference, take) if reference else None,
            "utmos": similarity.naturalness(take)}


def speech_span(path: Path) -> tuple[float, float] | None:
    """Where speech starts and ends in a take: the first and last 10 ms frame
    within 30 dB of the peak."""
    import numpy as np
    from app.continuity import signals
    x = signals.load(path)
    if not len(x):
        return None
    hop = signals.RATE // 100
    frames = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2) + 1e-12) for i in range(0, len(x) - hop, hop)])
    if not len(frames):
        return None
    db = 20 * np.log10(frames)
    loud = np.nonzero(db > db.max() - 30)[0]
    return (loud[0] / 100, (loud[-1] + 1) / 100) if len(loud) else None


def plan_quality(items: Sequence[dict], statements: Sequence[dict], targets: Sequence[int], adds: int,
                 question: bool) -> dict:
    """Did the turn change only what was asked? Each live item is matched to
    the asked line it overlaps most (over half its span), or counted as an
    added line when it replaces no speech. The score is the matched items over
    the larger of asked and made; a question turn scores 1 only with no items."""
    live = [i for i in items if i.get("status") != "dismissed" and i.get("kind", "planned") == "planned"]
    if question:
        return {"score": 1.0 if not live else 0.0, "items": len(live), "outside": len(live), "missed": 0}

    def overlap(item: dict, line: dict) -> float:
        a, b = item["selection"]["start"], item["selection"]["end"]
        inter = max(0.0, min(b, line["end"]) - max(a, line["start"]))
        return inter / max(1e-6, line["end"] - line["start"])

    hit, outside, added = set(), 0, 0
    for item in live:
        best = max(range(len(statements)), key=lambda k: overlap(item, statements[k]), default=None)
        if best is not None and overlap(item, statements[best]) > 0.5 and item.get("mix") != "layer":
            if best in targets and best not in hit:
                hit.add(best)
            else:
                outside += 1
        elif best is not None and any(overlap(item, s) > 0.1 for s in statements) and item.get("mix") != "layer":
            outside += 1
        else:
            added += 1
    good = len(hit) + min(added, adds)
    outside += max(0, added - adds)
    asked = len(targets) + adds
    return {"score": round(good / max(asked, good + outside, 1), 3), "items": len(live), "outside": outside,
            "missed": asked - good}


def ledger(db: Path, project_id: str, since: str) -> dict:
    """The app's own ledger for one video from `since`: USD by what, and the total."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT what, SUM(usd), SUM(units) FROM usage WHERE project_id = ? AND at >= ? GROUP BY what",
                            (project_id, since)).fetchall()
    finally:
        conn.close()
    by = {w: round(u or 0.0, 5) for w, u, _ in rows}
    return {"total": round(sum(by.values()), 5), "by": by, "units": {w: n for w, _, n in rows}}


def spent_today(db: Path, day: str) -> float:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return float(conn.execute("SELECT COALESCE(SUM(usd), 0) FROM usage WHERE at >= ?", (day,)).fetchone()[0])
    finally:
        conn.close()


_REQUEST = re.compile(r"agent request: input (\d+), cache read (\d+), cache write (\d+), output (\d+)")


def requests_in_log(text: str) -> list[dict]:
    """The agent's requests a turn made, from the backend log's own lines."""
    return [{"input": int(a), "cache_read": int(b), "cache_write": int(c), "output": int(d)}
            for a, b, c, d in _REQUEST.findall(text)]


def candidate_audio(db: Path, project_id: str, candidate_id: str) -> Path | None:
    import json
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT body FROM candidates WHERE project_id = ? AND candidate_id = ?",
                           (project_id, candidate_id)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    body = json.loads(row[0])
    path = (body.get("audio") or {}).get("path")
    return Path(path) if path and Path(path).exists() else None


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="ave-eval-"))
