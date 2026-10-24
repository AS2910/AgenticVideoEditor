"""The eval clips: the sample ad as it ships, and two clips made from it.

- `ad.mp4`: frontend/public/sample-ad.mp4, one line ("Get 20% off today only").
- `chai.mp4`: five lines of a two-person chai stall ad over the ad's picture,
  spoken by the system voices (macOS `say`: Tara and Aman, both en_IN), so it
  needs no vendor and is the same every time it is built.
- `silent.mp4`: the after-picture of the sample ad, looped to 6 s, no speech.

The built files are committed (they are small), so a run never needs `say`;
`python -m evals clips` rebuilds them on a Mac. `transcripts.json` beside them
holds each clip's words as made (keyed by the file's sha256): the eval
backend's mock transcriber reads it (AVE_KNOWN_TRANSCRIPTS), so the clips need
no paid transcription and their words are exact.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CLIPS = Path(__file__).resolve().parent / "clips"
PUBLIC = BACKEND.parent / "frontend" / "public"

# (speaker voice, words); a 0.6 s pause after each line.
CHAI = (
    ("Tara", "Is the masala chai fresh today?"),
    ("Aman", "Fresh every morning, made with ginger."),
    ("Tara", "How much for two cups?"),
    ("Aman", "Forty rupees, and the biscuits are free."),
    ("Tara", "Perfect, I will take two."),
)
PAUSE = 0.6
LEAD = 0.4
# The sample ad's words as Whisper gave them (app/bench/corpus.py, live 2026-09-23).
AD_WORDS = (("Get", 0.0, 0.24), ("20%", 0.24, 0.56), ("off", 0.96, 1.2), ("today", 1.2, 1.46), ("only", 1.46, 1.82))


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _line_words(text: str, start: float, end: float, speaker: str) -> list[list]:
    """Word times spread over the line by letters: rough, but every word sits inside its line."""
    tokens = [t.strip(",.?!") for t in text.split()]
    total = sum(len(t) for t in tokens) or 1
    out, at = [], start
    for t in tokens:
        step = (end - start) * len(t) / total
        out.append([t, round(at, 3), round(at + step, 3), speaker])
        at += step
    return out


def _chai(dest: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        parts, words, statements, at = [], [], [], LEAD
        for n, (who, line) in enumerate(CHAI):
            aiff = Path(tmp) / f"{n}.aiff"
            subprocess.run(["say", "-v", who, "-o", str(aiff), line], check=True)
            spoken = _seconds(aiff)
            speaker = "A" if who == "Tara" else "B"
            words += _line_words(line, at, at + spoken, speaker)
            statements.append([line, round(at, 3), round(at + spoken, 3), speaker])
            at += spoken + PAUSE
            wav = Path(tmp) / f"{n}.wav"
            _ff("-i", str(aiff), "-af", f"apad=pad_dur={PAUSE}", "-ar", "48000", "-ac", "1", str(wav))
            parts.append(wav)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        speech = Path(tmp) / "speech.wav"
        _ff("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(speech))
        # A short lead-in so the first word is not on frame zero.
        _ff("-stream_loop", "-1", "-i", str(PUBLIC / "sample-ad.mp4"), "-i", str(speech),
            "-filter_complex", "[1:a]adelay=400|400[a]", "-map", "0:v", "-map", "[a]", "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", str(dest))
    return {"words": words, "statements": statements}


def _silent(dest: Path) -> None:
    _ff("-stream_loop", "-1", "-i", str(PUBLIC / "sample-ad-after.mp4"), "-f", "lavfi",
        "-i", "anullsrc=r=48000:cl=mono", "-map", "0:v", "-map", "1:a", "-t", "6",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", str(dest))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> list[Path]:
    CLIPS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PUBLIC / "sample-ad.mp4", CLIPS / "ad.mp4")
    chai = _chai(CLIPS / "chai.mp4")
    _silent(CLIPS / "silent.mp4")
    known = {
        _sha(CLIPS / "ad.mp4"): {"clip": "ad.mp4", "words": [[w, s, e, "A"] for w, s, e in AD_WORDS],
                                 "statements": [["Get 20% off today only.", 0.0, 1.82, "A"]]},
        _sha(CLIPS / "chai.mp4"): {"clip": "chai.mp4", **chai},
        _sha(CLIPS / "silent.mp4"): {"clip": "silent.mp4", "words": [], "statements": []},
    }
    (CLIPS / "transcripts.json").write_text(json.dumps(known, ensure_ascii=False, indent=1))
    return [CLIPS / n for n in ("ad.mp4", "chai.mp4", "silent.mp4", "transcripts.json")]


def path(name: str) -> Path:
    p = CLIPS / name
    if not p.exists():
        raise SystemExit(f"{p} is missing; run `python -m evals clips` on a Mac")
    return p
