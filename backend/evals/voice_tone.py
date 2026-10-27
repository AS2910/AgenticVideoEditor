"""The voice tone eval (run 5 item 7): the same lines voiced the old way and the new way.

    python -m evals voice-tone --clip <video> --transcript <words.json> --voice <clone id> \\
        [--stems <dir with vocals.wav and accompaniment.wav>] [--only 1 3] --budget-chars 2000

Real ElevenLabs speech (the key from the environment), nothing else paid: no
agent, no transcription. Each line is a small change of words in a real clip,
voiced through `run_edit` exactly as the app does, twice:
- **old**: the measured engine as it was (AVE_VOICE_TONE=0): no delivery
  reference, no refusal for delivery, no room on the take, hard-tiled room tone;
- **new**: run 5 item 7 on: the first take follows the original line's delivery,
  a take outside the speaker's range is refused and retaken steered back, the
  pick ranks delivery, the room goes on the take.

Both are scored on the same yardstick, from what the user would hear: SIM-o and
UTMOS (local models), the prosody distance to the original line, the speech
level against the neighbouring lines (loudness delta, dB) and the spoken length
against the original line's (duration error, s). Each line is also cut in
context (1.5 s either side, rendered through the export's own splice) for the
A/B page, into `results/voice-ab/<run>/`.

Characters billed are counted per method from the adapter's budget, and priced
at the app's estimate rate (AVE_ELEVENLABS_USD_PER_1K, $0.30 a thousand).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from app.adapters.elevenlabs import ElevenLabsVoiceAdapter
from app.adapters.mock import MockLipSyncAdapter
from app.budget import VoiceBudget
from app.config import DEFAULT_ELEVENLABS_USD_PER_1K, DEFAULT_FIT_TOLERANCE, DEFAULT_MAX_REGENERATIONS, DEFAULT_TAKES_PER_LINE
from app.continuity import prosody, signals
from app.continuity.measured import MeasuredContinuityEngine
from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection, Source, Transcript, Word
from app.media import ffmpeg
from app.media.stems import Stems
from app.orchestrator.pipeline import run_edit
from app.render import compose
from app.render.renderer import render
from app.store.artifacts import ArtifactStore
from evals.metrics import speech_span

RESULTS = Path(__file__).resolve().parent / "results"
CONTEXT = 1.5

# The owl story (p66, 60 s, one speaker over a quiet music bed): six small
# changes of words, each inside one line.
STORY_LINES = (
    (10.96, 14.90, "That spring day was very hot and the dry fields were dusty"),
    (15.70, 19.02, "Kaju the crow flew all morning and he grew very thirsty"),
    (27.10, 29.52, "Then he saw a little pot under a tree"),
    (37.56, 39.36, "He sat and thought very hard"),
    (50.64, 53.32, "The cool water rose right to the top"),
    (58.08, 59.70, "Think hard and you will find a way"),
)


def _transcript(path: Path) -> Transcript:
    d = json.loads(path.read_text())
    return Transcript(words=tuple(Word(w["text"], w["start"], w["end"], w.get("speaker")) for w in d["words"]))


def _said(t: Transcript, a: float, b: float) -> str:
    return " ".join(w.text for w in t.words if w.start >= a - 0.02 and w.end <= b + 0.02)


def _scores(src: str, t: Transcript, plan: EditPlan, take: Path, report) -> dict:
    """The yardstick both methods are read on, from the take the user hears."""
    engine = MeasuredContinuityEngine(ArtifactStore(tempfile.mkdtemp()), tone=True)
    neighbours, reference = engine.deliveries(src, t, plan)
    x = signals.load(take)
    verdict = prosody.judge(prosody.measure(x), reference, neighbours)
    levels = [d.level for d in neighbours if d.level is not None]
    level = signals.speech_level_db(x)
    span = speech_span(take)
    with tempfile.TemporaryDirectory() as tmp:
        orig, _ = ffmpeg.extract_segment(src, Path(tmp) / "o.wav", plan.selection.start, plan.selection.end)
        o_span = speech_span(orig)
    duration_error = abs((span[1] - span[0]) - (o_span[1] - o_span[0])) if span and o_span else None
    return {
        "sim_o": report.voice_match, "utmos": report.naturalness,
        "prosody_distance": verdict.distance,
        "loudness_delta_db": round(level - float(np.median(levels)), 2) if level is not None and levels else None,
        "duration_error_s": round(duration_error, 3) if duration_error is not None else None,
        "outside": list(verdict.outside),
    }


def _in_context(source: Source, plan: EditPlan, audio: MediaArtifact | None, stems: Stems | None, dest: Path) -> Path:
    """The line with 1.5 s either side as the export would play it (the original when `audio` is None)."""
    base = compose.decode(source.media.path, channels=1)
    out = base
    if audio is not None:
        edit = ApprovedEdit("e", "c", plan, audio, audio)
        room = compose.Room.prepare(stems, 1, len(base))
        out = compose.splice(base, render(source, [edit]).segments, room)
    a = max(0, round((plan.selection.start - CONTEXT) * compose.OUT_RATE))
    b = min(len(out), round((plan.selection.end + CONTEXT) * compose.OUT_RATE))
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "x.wav"
        compose._write(wav, out[a:b])
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "96k", str(dest)], check=True)
    return dest


# Methods: the measured engine's switches (tone, room on the take, first-take reference).
METHODS = {
    "old": dict(tone=False),
    "new": dict(tone=True),               # as shipped: the reference follows AVE_VOICE_TONE_REFERENCE
    "ref": dict(tone=True, reference=True),
    "noref": dict(tone=True, reference=False),
    "noroom": dict(tone=True, room=False),
}


def run(clip: Path, transcript: Path, voice: str, stems_dir: Path | None, only: list[int] | None,
        budget_chars: int, label: str = "", methods: tuple[str, ...] = ("old", "new")) -> Path:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set (load it for this process only).")
    t = _transcript(transcript)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = f"{stamp}-{label or 'voice-tone'}"
    out_dir = RESULTS / "voice-ab" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="voice-tone-"))
    store = ArtifactStore(work)
    usd_per_1k = float(os.environ.get("AVE_ELEVENLABS_USD_PER_1K") or DEFAULT_ELEVENLABS_USD_PER_1K)
    budget = VoiceBudget(ceiling=budget_chars, usd_per_1k=usd_per_1k)
    stems = Stems(stems_dir / "vocals.wav", stems_dir / "accompaniment.wav") if stems_dir else None
    duration = ffmpeg.duration_of(clip)
    media = MediaArtifact("video", "v" * 64, str(clip), duration, clip.suffix.lstrip("."))
    trials, ledger = [], []
    for n, (start, end, text) in enumerate(STORY_LINES, 1):
        if only and n not in only:
            continue
        before = _said(t, start, end)
        files = {"original": f"t{n}-original.m4a"}
        scores = {}
        _in_context(Source("ctx", clip.name, duration, media), EditPlan(Selection(start, end), text, voice), None, stems,
                    out_dir / files["original"])
        for method in methods:
            pid = f"{method}{n}"
            source = Source(pid, clip.name, duration, media)
            adapter = ElevenLabsVoiceAdapter(key, store, budget, model="eleven_multilingual_v2", voice_id=voice,
                                             takes_per_line=DEFAULT_TAKES_PER_LINE, fit_tolerance=DEFAULT_FIT_TOLERANCE)
            adapter.register_clone(voice)
            engine = MeasuredContinuityEngine(store, **METHODS[method])
            plan = EditPlan(Selection(start, end), text, voice)
            began = time.time()
            try:
                cand = run_edit(f"c{pid}", plan, source, adapter, MockLipSyncAdapter(store), engine, transcript=t,
                                max_regenerations=DEFAULT_MAX_REGENERATIONS, route="auto")
            except Exception as exc:  # noqa: BLE001 - one line failing is a result, not the end of the run
                ledger.append({"line": n, "method": method, "chars": budget.spent(pid),
                               "usd": round(budget.spent(pid) * usd_per_1k / 1000, 4), "error": type(exc).__name__})
                print(f"line {n} {method}: failed ({type(exc).__name__}: {exc})")
                scores[method] = None
                continue
            chars = budget.spent(pid)
            ledger.append({"line": n, "method": method, "chars": chars, "usd": round(chars * usd_per_1k / 1000, 4),
                           "seconds": round(time.time() - began, 1)})
            s = _scores(str(clip), t, plan, Path(cand.audio.path), cand.continuity)
            s.update({"passed": cand.continuity.passed, "fit_notes": list(cand.fit_notes), "roomed": bool(cand.plan.roomed),
                      "warnings": list(cand.continuity.warnings), "chars": chars})
            scores[method] = s
            files[method] = f"t{n}-{method}.m4a"
            _in_context(source, replace(cand.plan), cand.audio, stems, out_dir / files[method])
            print(f"line {n} {method}: {chars} chars, SIM-o {s['sim_o']}, UTMOS {s['utmos']}, "
                  f"distance {s['prosody_distance']}, loudness {s['loudness_delta_db']} dB, length {s['duration_error_s']} s")
        if all(scores.get(m) for m in methods):
            trials.append({"id": f"t{n}", "speaker": "A", "before": before, "after": text, "start": start, "end": end,
                           "files": files, "scores": scores})
    summary = _summary(trials, methods)
    spent = sum(r["usd"] for r in ledger)
    data = {"clip": clip.name, "made_at": stamp, "summary": summary, "ledger": ledger, "usd": round(spent, 4),
            "usd_per_1k_chars": usd_per_1k, "trials": trials}
    (out_dir / "trials.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"summary": summary, "usd": round(spent, 4)}, indent=2))
    return out_dir


def _summary(trials: list[dict], methods=("old", "new")) -> dict:
    """Mean of each score per method, over the lines both methods voiced."""
    keys = ("sim_o", "utmos", "prosody_distance", "loudness_delta_db", "duration_error_s")
    out = {}
    for method in methods:
        row = {}
        for k in keys:
            vals = [abs(t["scores"][method][k]) if k == "loudness_delta_db" else t["scores"][method][k]
                    for t in trials if t["scores"][method].get(k) is not None]
            row[k if k != "loudness_delta_db" else "abs_loudness_delta_db"] = round(sum(vals) / len(vals), 3) if vals else None
        row["passed"] = sum(1 for t in trials if t["scores"][method]["passed"])
        row["lines"] = len(trials)
        out[method] = row
    return out
