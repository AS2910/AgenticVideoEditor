"""The golden corpus: clips with labelled edits, each built on demand.

Two clips ship with the repo and need nothing: the sample ad (real speech, the
word times Whisper gave it, and the recorded ElevenLabs take), and a synthetic
two-speaker clip made by ffmpeg (tone bursts at two pitches with pauses — not
speech, but every measurement runs on it, and it is bit-exact run to run).
Real clips go in `backend/bench/clips/` (git-ignored) with a manifest beside
each; see `load_manifest`.

A case's `label` says what the measurements must find:
- `good`  — the fitted take must pass continuity;
- `bad`   — it must fail (pitch off, drowned in noise);
- `ask`   — the take does not fit the slot and the ladder must say so
            (SpanMismatch) rather than stretch speech past its limits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from app.bench import BACKEND
from app.domain.models import Selection, Transcript, Word
from app.media import ffmpeg

SAMPLE_AD = BACKEND.parent / "frontend" / "public" / "sample-ad.mp4"
FIXTURE_PCM = BACKEND / "tests" / "fixtures" / "elevenlabs-tts.pcm"
RATE = 24000   # takes are the vendor's mono 24 kHz

# Word timings Whisper returned for the sample ad (live, 2026-09-23).
SAMPLE_WORDS = Transcript(words=(
    Word("Get", 0.0, 0.24), Word("20", 0.24, 0.56), Word("off", 0.96, 1.2),
    Word("today", 1.2, 1.46), Word("only", 1.46, 1.82),
))
SAMPLE_SLOT = Selection(0.24, 1.2)

TakeBuilder = Callable[[Path], Path]


@dataclass(frozen=True)
class Case:
    name: str
    clip: Path
    transcript: Transcript
    selection: Selection
    take: TakeBuilder          # writes the take as a mono 24 kHz WAV into the directory given
    label: str                 # good | bad | ask
    mix: str = "replace"
    tags: tuple[str, ...] = field(default=())


# ── the sample ad ───────────────────────────────────────────────────────────────

def _segment(clip: Path, start: float, end: float) -> TakeBuilder:
    def build(d: Path) -> Path:
        path, _ = ffmpeg.extract_segment(clip, d / "line.wav", start, end, sample_rate=RATE)
        return path
    return build


def _pitched(clip: Path, start: float, end: float, semitones: float) -> TakeBuilder:
    def build(d: Path) -> Path:
        line = _segment(clip, start, end)(d)
        factor = 2 ** (semitones / 12)
        dest = d / f"pitched{semitones:+}.wav"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN, "-i", str(line),
            "-af", f"asetrate={RATE * factor:.0f},aresample={RATE},atempo={1 / factor:.6f}",
            "-ac", "1", "-c:a", "pcm_s16le", *ffmpeg._BITEXACT_OUT, str(dest),
        ])
        return dest
    return build


def _noisy(clip: Path, start: float, end: float, amount: float = 0.05) -> TakeBuilder:
    def build(d: Path) -> Path:
        from app.continuity.measured import _read_wav, _write_wav
        x, rate = _read_wav(str(_segment(clip, start, end)(d)))
        x = x + np.random.default_rng(0).standard_normal(x.size).astype(np.float32) * amount
        _write_wav(d / "noisy.wav", x, rate)
        return d / "noisy.wav"
    return build


def _stretched(clip: Path, start: float, end: float, factor: float) -> TakeBuilder:
    """The line itself, `factor` times as long (pitch kept): a take that runs long or short."""
    def build(d: Path) -> Path:
        line = _segment(clip, start, end)(d)
        dest = d / f"x{factor:.2f}.wav"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN, "-i", str(line),
            "-af", ffmpeg.atempo_chain(1 / factor), "-ac", "1", "-c:a", "pcm_s16le",
            *ffmpeg._BITEXACT_OUT, str(dest),
        ])
        return dest
    return build


def _elevenlabs_fixture(d: Path) -> Path:
    raw, _ = ffmpeg.pcm_to_wav(FIXTURE_PCM.read_bytes(), d / "eleven.wav", RATE)
    return raw


def sample_ad_cases() -> list[Case]:
    s, e = SAMPLE_SLOT.start, SAMPLE_SLOT.end
    clip = SAMPLE_AD
    return [
        Case("sample-ad · the speaker's own line", clip, SAMPLE_WORDS, SAMPLE_SLOT, _segment(clip, s, e), "good", tags=("speech",)),
        Case("sample-ad · ElevenLabs stock voice, 30% off", clip, SAMPLE_WORDS, SAMPLE_SLOT, _elevenlabs_fixture, "good", tags=("speech", "vendor")),
        Case("sample-ad · own line, runs 12% long", clip, SAMPLE_WORDS, SAMPLE_SLOT, _stretched(clip, s, e, 1.12), "good", tags=("speech", "long")),
        Case("sample-ad · own line, runs 12% short", clip, SAMPLE_WORDS, SAMPLE_SLOT, _stretched(clip, s, e, 0.88), "good", tags=("speech", "short")),
        Case("sample-ad · own line, runs 60% long", clip, SAMPLE_WORDS, SAMPLE_SLOT, _stretched(clip, s, e, 1.6), "ask", tags=("speech", "long")),
        Case("sample-ad · pitched up 6 semitones", clip, SAMPLE_WORDS, SAMPLE_SLOT, _pitched(clip, s, e, 6), "bad", tags=("speech", "pitch")),
        Case("sample-ad · pitched down 6 semitones", clip, SAMPLE_WORDS, SAMPLE_SLOT, _pitched(clip, s, e, -6), "bad", tags=("speech", "pitch")),
        Case("sample-ad · drowned in noise", clip, SAMPLE_WORDS, SAMPLE_SLOT, _noisy(clip, s, e), "bad", tags=("speech", "noise")),
        Case("sample-ad · a line added after, no pause to stretch", clip, SAMPLE_WORDS, SAMPLE_SLOT, _segment(clip, s, e), "good", mix="concatenate", tags=("speech", "insert")),
    ]


# ── the synthetic two-speaker clip ───────────────────────────────────────────────

SYNTH_A_HZ, SYNTH_B_HZ = 220.0, 330.0
# (speaker, start, end): three bursts with pauses between — A, B, A.
SYNTH_LINES = (("A", 0.3, 1.1), ("B", 1.6, 2.4), ("A", 2.9, 3.7))
SYNTH_DURATION = 4.0


def _burst(d: Path, name: str, hz: float, seconds: float, gain: float = 1.0) -> Path:
    """A tone burst, `gain` times the generator's level (kept under full scale)."""
    path, _ = ffmpeg.generate_tone(d / name, seconds, hz, sample_rate=RATE)
    if gain != 1.0:
        from app.continuity.measured import _read_wav, _write_wav
        x, rate = _read_wav(str(path))
        x = x * gain
        peak = float(np.max(np.abs(x)))
        if peak > 0.98:
            raise ValueError(f"a burst at gain {gain} would clip (peak {peak:.2f})")
        _write_wav(path, x, rate)
    return path


def build_synthetic_clip(d: Path) -> Path:
    """A 4 s H.264 clip whose soundtrack is three tone bursts: A, B, A."""
    video, _ = ffmpeg.generate_solid_video(d / "synth-v.mp4", SYNTH_DURATION, color="0x203040")
    parts = []
    for i, (who, start, end) in enumerate(SYNTH_LINES):
        hz = SYNTH_A_HZ if who == "A" else SYNTH_B_HZ
        parts.append((start, _burst(d, f"burst{i}.wav", hz, end - start)))
    # Lay the bursts on a silent bed at 48 kHz stereo-agnostic mono.
    from app.render.compose import OUT_RATE, _write, decode
    bed = np.zeros((int(SYNTH_DURATION * OUT_RATE), 1), dtype=np.float32)
    for start, path in parts:
        x = decode(path, channels=1)
        i0 = int(start * OUT_RATE)
        bed[i0:i0 + len(x)] += x[: len(bed) - i0] * 0.5
    _write(d / "synth-a.wav", bed)
    dest = d / "synth.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN,
        "-i", str(video), "-i", str(d / "synth-a.wav"),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", *ffmpeg._BITEXACT_OUT, str(dest),
    ])
    return dest


def synthetic_cases(clip: Path) -> list[Case]:
    words = Transcript(words=tuple(
        Word(f"{who}{i}", start, end, speaker=who) for i, (who, start, end) in enumerate(SYNTH_LINES)
    ))
    first = Selection(SYNTH_LINES[0][1], SYNTH_LINES[0][2])
    span = first.end - first.start
    a = lambda d: _burst(d, "a.wav", SYNTH_A_HZ, span)                        # noqa: E731
    b = lambda d: _burst(d, "b.wav", SYNTH_B_HZ, span)                        # noqa: E731
    loud = lambda d: _burst(d, "loud.wav", SYNTH_A_HZ, span, gain=1.5)        # noqa: E731  (+9.5 dB over the context: corrected)
    long = lambda d: _burst(d, "long.wav", SYNTH_A_HZ, span * 1.5)            # noqa: E731
    return [
        Case("synth · A's own pitch", clip, words, first, a, "good", tags=("synthetic",)),
        Case("synth · B's pitch in A's slot", clip, words, first, b, "bad", tags=("synthetic", "pitch")),
        Case("synth · A, 9.5 dB too loud (corrected)", clip, words, first, loud, "good", tags=("synthetic", "level")),
        Case("synth · A, runs 50% long", clip, words, first, long, "ask", tags=("synthetic", "long")),
        # Phase 16: the 0.5 s pause after A's line stretches (and loops) to make room; nothing is frozen.
        Case("synth · a line added after A, over the pause", clip, words, first, long, "good", mix="concatenate", tags=("synthetic", "insert", "living")),
    ]


# ── real clips the user drops in ────────────────────────────────────────────────

def load_manifest(path: Path) -> list[Case]:
    """`<name>.json` beside a clip: {"clip": "x.mp4", "words": [[text, start, end, speaker?]...],
    "edits": [{"name", "start", "end", "take": "take.wav", "label": "good|bad|ask", "mix"?}]}."""
    data = json.loads(path.read_text())
    folder = path.parent
    words = Transcript(words=tuple(Word(w[0], float(w[1]), float(w[2]), w[3] if len(w) > 3 else None) for w in data["words"]))
    cases = []
    for edit in data["edits"]:
        take = folder / edit["take"]
        cases.append(Case(
            f"{path.stem} · {edit['name']}", folder / data["clip"], words,
            Selection(float(edit["start"]), float(edit["end"])),
            (lambda t: (lambda d: t))(take), edit["label"], edit.get("mix", "replace"), tags=("real",),
        ))
    return cases


def build(workdir: Path, clips_dir: Path | None = None) -> list[Case]:
    """Every case: the sample ad's, the synthetic clip's (built into `workdir`),
    and one per manifest in `clips_dir`."""
    cases = sample_ad_cases() if SAMPLE_AD.exists() else []
    synth = workdir / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    cases += synthetic_cases(build_synthetic_clip(synth))
    if clips_dir and clips_dir.exists():
        for manifest in sorted(clips_dir.glob("*.json")):
            cases += load_manifest(manifest)
    return cases
