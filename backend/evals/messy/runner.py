"""Score the messy variants: where transcription, voice matching and timing break.

Per variant, through the app's own code (no server):

- **bed**: `media.bed.detect`, against whether the variant really has one.
- **transcription**: the real Whisper adapter (`WhisperTranscriptionAdapter`,
  diarization included) when OPENAI_API_KEY is set. Every vendor response is
  kept under `out/cache/` by the audio's sha, so a re-score after a fix pays
  only for audio that changed. Scored as word recall against the clean words,
  invented words, lines lost, and speaker labels.
- **timing**: the span Voltage would replace for each line (the line's words
  as transcribed) against where the speech really starts and ends (measured on
  the clean audio). A line breaks when either edge is off by more than
  `EDGE_S`, or the line is missing.
- **voice matching**: the measured continuity check (`MeasuredContinuity`,
  WavLM SIM-o and UTMOS when the `measure` extra is installed) on a replacement
  of two lines, with the clean truth as the transcript so only the audio
  differs. Two takes: the speaker's own clean line (a perfect take that must
  pass) and a real ElevenLabs take of the same words (paid once, kept in the
  cache, reused on every variant).
- **bed kept**: for variants with a bed, the line replaced through the
  compositor's own `splice`, with and without stems: how much of the true bed
  plays under the new line, and how much of the old voice leaks through.

Paid calls are written to the ledger in the result (`spend`).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.domain.models import (
    EditPlan,
    MediaArtifact,
    Selection,
    Source,
    Transcript,
    Word,
)
from app.media import bed as bedmod
from app.media import ffmpeg
from evals.messy import variants as V

RESULTS = V.HERE / "results"
CACHE = V.OUT / "cache"
EDGE_S = 0.20                  # a replaced span this far off a line's real edge clips or leaves speech
WHISPER_USD_PER_MIN = 0.006
DIARIZE_USD_PER_MIN = 0.006
ELEVEN_USD_PER_1K = 0.30
# The lines replaced for voice matching: (line index, stock voice for the real take).
# Speaker B (Aman): the only speaker whose lines have their own speech within the context window.
VOICE_LINES = ((1, "pNInz6obpgDQGcFsmJgB"), (3, "pNInz6obpgDQGcFsmJgB"))


class Ledger:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, vendor: str, what: str, amount: float, unit: str, usd: float, cached: bool) -> None:
        self.rows.append({"vendor": vendor, "what": what, "amount": round(amount, 3), "unit": unit,
                          "usd": 0.0 if cached else round(usd, 5), "cached": cached})

    @property
    def usd(self) -> float:
        return round(sum(r["usd"] for r in self.rows), 4)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cached(kind: str, audio: Path, call):
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"{kind}-{_sha(audio)[:20]}.json"
    if dest.exists():
        return json.loads(dest.read_text()), True
    out = call()
    dest.write_text(json.dumps(out))
    return out, False


# Whisper writes numbers as digits; the truth spells them.
_NUMBERS = {"40": "forty", "2": "two"}


def _norm(text: str) -> list[str]:
    return [_NUMBERS.get(t, t) for t in re.sub(r"[^\w\s]", " ", text.lower()).split() if t]


# ── truth ────────────────────────────────────────────────────────────────────

def _speech_edges(clean: np.ndarray, start: float, end: float) -> tuple[float, float]:
    """Where speech really starts and ends inside a line's window, on the clean audio."""
    a, b = int(max(0.0, start - 0.1) * V.RATE), int((end + 0.1) * V.RATE)
    seg = clean[a:b]
    hop = V.RATE // 100
    n = len(seg) // hop
    db = 20 * np.log10(np.sqrt(np.mean(seg[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    on = np.flatnonzero(db > db.max() - 35)
    return a / V.RATE + on[0] * hop / V.RATE, a / V.RATE + (on[-1] + 1) * hop / V.RATE


def truth_lines(clean: np.ndarray) -> list[dict]:
    out = []
    for text, s, e, spk in V.truth()["statements"]:
        rs, re_ = _speech_edges(clean, s, e)
        out.append({"text": text, "start": round(rs, 3), "end": round(re_, 3), "speaker": spk, "words": _norm(text)})
    return out


def truth_transcript(lines: list[dict]) -> Transcript:
    words = tuple(Word(w, s, e, spk) for w, s, e, spk in V.truth()["words"])
    from app.domain.models import Statement
    return Transcript(words=words, statements=tuple(Statement(ln["text"], ln["start"], ln["end"], ln["speaker"]) for ln in lines))


# ── transcription ────────────────────────────────────────────────────────────

def transcriber(ledger: Ledger, seconds: float):
    """The real adapter with cached vendor calls, or None without a key."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    from app.adapters import openai_whisper as ow

    def post(audio: Path, api_key: str, timeout: float) -> dict:
        out, hit = _cached("whisper", audio, lambda: ow._post(audio, api_key, timeout))
        ledger.add("openai", "whisper-1", seconds / 60, "minutes", seconds / 60 * WHISPER_USD_PER_MIN, hit)
        return out

    def post_diarize(audio: Path, api_key: str, timeout: float) -> dict:
        out, hit = _cached("diarize", audio, lambda: ow._post_diarize(audio, api_key, timeout))
        ledger.add("openai", ow.DIARIZE_MODEL, seconds / 60, "minutes", seconds / 60 * DIARIZE_USD_PER_MIN, hit)
        return out

    return ow.WhisperTranscriptionAdapter(key, post=post, post_diarize=post_diarize)


def score_transcript(t: Transcript, lines: list[dict]) -> dict:
    truth_words = [w for ln in lines for w in ln["words"]]
    owner = [i for i, ln in enumerate(lines) for _ in ln["words"]]
    got = [(tok, w) for w in t.words for tok in _norm(w.text)]
    sm = difflib.SequenceMatcher(a=truth_words, b=[g[0] for g in got], autojunk=False)
    matched: dict[int, list[Word]] = {}
    hits = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            hits += 1
            matched.setdefault(owner[blk.a + k], []).append(got[blk.b + k][1])
    timing, lost = [], 0
    labels: dict[str, dict[str, int]] = {}
    for i, ln in enumerate(lines):
        ws = matched.get(i, [])
        if len(ws) < max(1, len(ln["words"]) // 2):
            lost += 1
            timing.append({"line": i, "found": False})
            continue
        ds, de = ws[0].start - ln["start"], ws[-1].end - ln["end"]
        timing.append({"line": i, "found": True, "start_err": round(ds, 3), "end_err": round(de, 3),
                       "ok": abs(ds) <= EDGE_S and abs(de) <= EDGE_S})
        for w in ws:
            labels.setdefault(ln["speaker"], {}).setdefault(w.speaker or "?", 0)
            labels[ln["speaker"]][w.speaker or "?"] += 1
    # Speakers: each true speaker's most common label; right when the two are told apart.
    best = {s: max(c, key=c.get) for s, c in labels.items()}
    distinct = len(set(best.values())) == len(best) and "?" not in best.values()
    right = sum(c.get(best[s], 0) for s, c in labels.items()) if distinct else 0
    total = sum(sum(c.values()) for c in labels.values()) or 1
    return {
        "recall": round(hits / len(truth_words), 3),
        "invented": len(got) - hits,
        "lines_lost": lost,
        "lines_seen": len(t.statements),
        "speakers_ok": round(right / total, 3),
        "timing": timing,
        "timing_broken": sum(1 for x in timing if not x.get("ok")),
        "text": " | ".join(s.text for s in t.statements),
    }


# ── voice matching ───────────────────────────────────────────────────────────

def _wav_cut(src: Path, start: float, end: float, dest: Path) -> Path:
    ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
                                "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(dest)])
    return dest


def real_take(ledger: Ledger, text: str, voice_id: str, dest: Path) -> Path | None:
    """One ElevenLabs take of `text` (kept in the cache: paid once ever)."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    CACHE.mkdir(parents=True, exist_ok=True)
    kept = CACHE / f"take-{hashlib.sha256((voice_id + text).encode()).hexdigest()[:20]}.wav"
    if kept.exists():
        ledger.add("elevenlabs", "tts", len(text), "chars", 0.0, True)
        dest.write_bytes(kept.read_bytes())
        return dest
    if not key:
        return None
    from app.adapters import elevenlabs as el
    body = {"text": text, "model_id": "eleven_multilingual_v2"}
    try:
        status, content, err = el._post(voice_id, body, key, 60.0)
    except el.VoiceError as exc:
        print(f"elevenlabs: {exc}")
        return None
    if status != 200:
        print(f"elevenlabs {status}: {err[:200]}")
        return None
    pcm, _ = el.decode_response(content)
    ledger.add("elevenlabs", "tts", len(text), "chars", len(text) / 1000 * ELEVEN_USD_PER_1K, False)
    import wave
    with wave.open(str(kept), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    dest.write_bytes(kept.read_bytes())
    return dest


def voice_matching(source: Source, transcript: Transcript, lines: list[dict], takes: dict, store, *,
                   context_media: Path | None = None) -> list[dict]:
    from app.continuity.measured import MeasuredContinuityEngine as MeasuredContinuity
    engine = MeasuredContinuity(store)
    src = source if context_media is None else Source(source.project_id, source.filename, source.duration,
                                                      MediaArtifact(path=str(context_media), kind="video", sha256="ctx",
                                                                    container="mp4", duration=source.duration))
    out = []
    for (i, _), per in zip(VOICE_LINES, takes.values()):
        ln = lines[i]
        plan = EditPlan(Selection(ln["start"], ln["end"]), ln["text"], "v")
        for kind, path in per.items():
            if path is None:
                continue
            art = MediaArtifact(path=str(path), kind="audio", sha256=_sha(path), container="wav",
                                duration=ffmpeg.duration_of(path))
            rep = engine.assess(src, transcript, plan, art).report
            out.append({"line": i, "take": kind, "passed": rep.passed, "voice_match": _r(rep.voice_match),
                        "prosody": _r(rep.prosody), "integration": _r(rep.audio_integration),
                        "naturalness": _r(rep.naturalness), "warnings": list(rep.warnings)})
    return out


def _r(x):
    return None if x is None else round(float(x), 3)


# ── the bed under a replaced line ────────────────────────────────────────────

def bed_kept(variant_mp4: Path, clean_mp4: Path, line: dict, take: Path, stems_dir: Path) -> dict:
    """Replace `line` through `render.compose.splice`, with and without stems.
    `bed` is how much of the true bed (variant minus clean) plays in the span,
    `old_voice` how much of the original speech leaks through (both 1.0 = all)."""
    from app.media import stems as stemsmod
    from app.render import compose as comp
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        base = comp.decode(variant_mp4)
        clean = comp.decode(clean_mp4)
        n = min(len(base), len(clean))
        base, clean = base[:n], clean[:n]
        true_bed = base - clean
        wav, _ = ffmpeg.extract_audio(variant_mp4, tmp / "src.wav", sample_rate=44100)
        t0 = time.time()
        st = stemsmod.separate(wav, stems_dir)
        seconds = round(time.time() - t0, 1)
        room = comp.Room.prepare(st, base.shape[1], n) if st else None
        edit = SimpleNamespace(audio=SimpleNamespace(path=str(take), sha256=_sha(take)), edit_id="e",
                               plan=SimpleNamespace(selection=SimpleNamespace(start=line["start"]), mix="replace"))
        seg = SimpleNamespace(kind="edited", edit=edit, start=line["start"], end=line["end"])
        out = {"separation_s": seconds, "stems": st is not None, "room": room is not None}
        i0, i1 = int((line["start"] + 0.05) * comp.OUT_RATE), int((line["end"] - 0.05) * comp.OUT_RATE)
        for label, r in (("without_stems", None), ("with_stems", room)):
            if label == "with_stems" and r is None:
                continue
            y = comp.splice(base, [seg], r)[i0:i1, 0]
            b, c = true_bed[i0:i1, 0], clean[i0:i1, 0]
            out[label] = {"bed": _r(float(np.dot(y, b) / (np.dot(b, b) or 1.0))),
                          "old_voice": _r(float(np.dot(y, c) / (np.dot(c, c) or 1.0)))}
        return out


# ── the run ──────────────────────────────────────────────────────────────────

def run(label: str, only: list[str] | None = None, *, budget: float = 1.0, voice: bool = True,
        bed: bool = True, transcribe_vocals: bool = False) -> Path:
    from app.store.artifacts import ArtifactStore
    ledger = Ledger()
    clean_mp4 = V.path_of(V.VARIANTS[0])
    if not clean_mp4.exists():
        V.build()
    work = Path(tempfile.mkdtemp(prefix="messy-"))
    store = ArtifactStore(work / "store")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "c.wav"
        ffmpeg._run(ffmpeg.FFMPEG, ["-y", "-loglevel", "error", "-i", str(clean_mp4), "-vn", "-ac", "1",
                                    "-ar", str(V.RATE), "-c:a", "pcm_s16le", str(d)])
        clean = V.read_wav(d)
    lines = truth_lines(clean)
    truth = truth_transcript(lines)
    takes: dict = {}
    for i, voice_id in VOICE_LINES:
        ln = lines[i]
        own = _wav_cut(clean_mp4, ln["start"], ln["end"], work / f"own{i}.wav")
        takes[i] = {"own": own, "real": real_take(ledger, ln["text"], voice_id, work / f"real{i}.wav") if voice else None}
    # A fresh cache per run, so separation times are real (not a cache hit).
    stems_root = work / "stems"
    rows = []
    for v in V.VARIANTS:
        if only and v.name not in only:
            continue
        mp4 = V.path_of(v)
        seconds = ffmpeg.duration_of(mp4)
        source = Source(project_id=f"messy-{v.name}", filename=mp4.name, duration=seconds,
                        media=MediaArtifact(path=str(mp4), kind="video", sha256=_sha(mp4), container="mp4", duration=seconds))
        row: dict = {"variant": v.name, "family": v.family, "what": v.what, "has_bed": v.bed}
        found = bedmod.detect(mp4)
        row["bed"] = found.as_dict() if found else None
        stems_dir = stems_root
        heard_from = mp4
        if transcribe_vocals and found is not None and found.present:
            from app.media import stems as stemsmod
            wav, _ = ffmpeg.extract_audio(mp4, work / f"{v.name}-44k.wav", sample_rate=44100)
            st = stemsmod.separate(wav, stems_dir)
            if st is not None:
                heard_from = st.vocals
        if ledger.usd < budget:
            tr = transcriber(ledger, seconds)
            if tr is not None:
                src_for_asr = source if heard_from == mp4 else Source(
                    source.project_id, source.filename, seconds,
                    MediaArtifact(path=str(heard_from), kind="audio", sha256="v", container="wav", duration=seconds))
                try:
                    heard = tr.transcribe(src_for_asr)
                    row["transcription"] = score_transcript(heard, lines)
                except Exception as exc:  # noqa: BLE001 - one variant failing is a finding, not a stop
                    row["transcription"] = {"error": str(exc)[:200]}
        else:
            row["transcription"] = {"error": "budget reached"}
        row["voice"] = voice_matching(source, truth, lines, takes, store)
        if bed and v.bed and v.family in ("music", "noise"):
            # Another voice's take (the real one, else line 1's own audio), so the old voice's leak is measurable.
            row["bed_kept"] = bed_kept(mp4, clean_mp4, lines[3], takes[3]["real"] or takes[1]["own"], stems_dir)
        rows.append(row)
        print(v.name, json.dumps({k: row[k] for k in ("bed",)}),
              {k: row.get("transcription", {}).get(k) for k in ("recall", "invented", "lines_lost", "timing_broken")},
              [(x["take"], x["passed"]) for x in row["voice"]], flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}-{label or 'run'}.json"
    out.write_text(json.dumps({"label": label, "at": stamp, "lines": lines, "rows": rows,
                               "spend": {"usd": ledger.usd, "calls": ledger.rows}}, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return out
