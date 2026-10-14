"""Stem separation (Phase 15c, optional extra `room`): the voice apart from the bed.

Demucs' two-stem `htdemucs` splits the original into vocals and everything
else. The compositor keeps the "everything else" of an edited span so music and
ambience carry on under the new line. Demucs is an optional extra, so every
failure here is a quiet `None` and the render falls back to today's path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MODEL = "htdemucs"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Stems:
    vocals: Path
    accompaniment: Path


def available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def _demucs(wav: Path, out_dir: Path) -> None:
    """Run demucs; it writes `<out_dir>/htdemucs/<name>/{vocals,no_vocals}.wav`."""
    subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", MODEL,
         "-o", str(out_dir), str(wav)],
        check=True, capture_output=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def separate(
    wav: Path, out_dir: Path, *, run: Callable[[Path, Path], None] | None = None,
) -> Stems | None:
    """Vocals and accompaniment of `wav`, cached under `out_dir/<sha256 of wav>/`.

    `run(wav, scratch_dir)` does the separation and leaves demucs' layout in
    `scratch_dir`; it is injectable so tests never load the model. Returns None
    when demucs is unavailable or anything goes wrong — never raises.
    """
    if run is None and not available():
        return None
    try:
        wav = Path(wav)
        home = Path(out_dir) / _sha256(wav)
        vocals, rest = home / "vocals.wav", home / "accompaniment.wav"
        if vocals.is_file() and rest.is_file():
            return Stems(vocals, rest)
        scratch = home / "work"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True, exist_ok=True)
        (run or _demucs)(wav, scratch)
        found = scratch / MODEL / wav.stem
        made_v, made_r = found / "vocals.wav", found / "no_vocals.wav"
        if not (made_v.is_file() and made_r.is_file()):
            shutil.rmtree(scratch, ignore_errors=True)
            return None
        made_v.replace(vocals)
        made_r.replace(rest)
        shutil.rmtree(scratch, ignore_errors=True)
        return Stems(vocals, rest)
    except Exception:  # noqa: BLE001 - separation is best-effort; the render goes on without it
        return None
