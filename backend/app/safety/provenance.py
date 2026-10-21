"""G6: provenance on every export: an invisible watermark and a C2PA-style manifest.

    watermarker.embed(src, dst, mark) -> None     dst carries the mark
    watermarker.read(path) -> str | None
    signer.sign(manifest) -> dict                 the signature block
    stamp(path, *, video_id, owner, watermarker, signer, source_sha=None) -> dict

`FakeWatermarker` writes the mark into the file's metadata (`comment`, with
ffmpeg, streams copied, so the picture and sound are untouched): it is
invisible but not robust, a real watermark lives in the audio and the
pixels and survives re-encoding (SETUP_NEEDED.md). `FakeSigner` signs the
manifest with an HMAC over its JSON with a local key and says it is a test
signature; real C2PA signing needs a certificate from a C2PA trust list.
The manifest is written beside the file as `<file>.c2pa.json`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from app.timefmt import now_iso

PREFIX = "voltage-wm:"
CLAIM_GENERATOR = "Voltage (AgenticVideoEditor)"


class Watermarker(Protocol):
    name: str

    def embed(self, src: Path, dst: Path, mark: str) -> None: ...

    def read(self, path: Path) -> str | None: ...


class C2PASigner(Protocol):
    name: str

    def sign(self, manifest: dict) -> dict: ...


class FakeWatermarker:
    name = "fake (metadata)"

    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe

    def embed(self, src: Path, dst: Path, mark: str) -> None:
        subprocess.run([self.ffmpeg, "-y", "-v", "error", "-i", str(src), "-map", "0", "-c", "copy",
                        "-metadata", f"comment={PREFIX}{mark}", "-movflags", "+faststart", str(dst)],
                       check=True, capture_output=True, timeout=120)

    def read(self, path: Path) -> str | None:
        out = subprocess.run([self.ffprobe, "-v", "error", "-show_entries", "format_tags=comment", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60)
        try:
            comment = (json.loads(out.stdout or "{}").get("format", {}).get("tags", {}) or {}).get("comment", "")
        except ValueError:
            return None
        return comment[len(PREFIX):] if comment.startswith(PREFIX) else None


class FakeSigner:
    name = "fake (HMAC, test mode)"

    def __init__(self, key: bytes) -> None:
        self.key = key

    def sign(self, manifest: dict) -> dict:
        body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        return {"alg": "HMAC-SHA256 (test, not a C2PA certificate)", "signer": self.name, "test_mode": True,
                "signature": hmac.new(self.key, body, hashlib.sha256).hexdigest()}

    def verify(self, manifest: dict, signature: dict) -> bool:
        return hmac.compare_digest(self.sign(manifest)["signature"], signature.get("signature", ""))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".c2pa.json")


def stamp(path: Path, *, video_id: str, owner: str, watermarker: Watermarker, signer: C2PASigner,
          source_sha: str | None = None) -> dict:
    """Mark `path` in place and write its manifest beside it. Returns
    {"mark", "manifest": path, "sha256"} (the sha of the marked file)."""
    mark = secrets.token_hex(8)
    tmp = path.with_name(path.stem + ".wm" + path.suffix)
    watermarker.embed(path, tmp, mark)
    shutil.move(str(tmp), str(path))
    digest = _sha(path)
    manifest = {
        "claim_generator": CLAIM_GENERATOR, "format": "video/mp4", "title": path.name, "created": now_iso(),
        "assertions": [
            {"label": "c2pa.actions", "data": {"actions": [
                {"action": "c2pa.edited", "softwareAgent": CLAIM_GENERATOR,
                 "description": "Lines re-voiced with synthetic speech made by Voltage."},
                {"action": "c2pa.watermarked", "parameters": {"watermarker": watermarker.name}}]}},
            {"label": "c2pa.ai_generated", "data": {"synthetic_voice": True}},
            {"label": "voltage.provenance", "data": {"video_id": video_id, "mark": mark}},
        ],
        "ingredients": [{"relationship": "parentOf", "sha256": source_sha}] if source_sha else [],
        "asset": {"sha256": digest},
    }
    signed = {"manifest": manifest, "signature": signer.sign(manifest)}
    manifest_path(path).write_text(json.dumps(signed, indent=2), encoding="utf-8")
    return {"mark": mark, "manifest": str(manifest_path(path)), "sha256": digest}
