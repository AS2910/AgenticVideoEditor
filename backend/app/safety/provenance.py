"""G6: provenance on every export: an invisible watermark and a C2PA-style manifest.

    watermarker.embed(src, dst, mark) -> None     dst carries the mark
    watermarker.read(path) -> str | None
    signer.sign(manifest) -> dict                 the signature block
    stamp(path, *, video_id, owner, watermarker, signer, source_sha=None, export=None) -> dict
    tag(path, tags) -> None                        container metadata written, streams copied
    read_tags(path) -> dict                        the container's metadata

`FakeWatermarker` writes the mark into the file's metadata (`comment`, with
ffmpeg, streams copied, so the picture and sound are untouched): it is
invisible but not robust, a real watermark lives in the audio and the
pixels and survives re-encoding (SETUP_NEEDED.md). `FakeSigner` signs the
manifest with an HMAC over its JSON with a local key and says it is a test
signature; real C2PA signing needs a certificate from a C2PA trust list.
The manifest is written beside the file as `<file>.c2pa.json`.

Voice consent V1, step 7: with `export` (`voices.cloning_verified` on for the
owner) the file also carries permanent metadata, in the container (`tag`,
after the watermark, which it keeps) and in the manifest (`voltage.export`):
the export id, Voltage, the time, and "contains AI-generated voice" when it
does; the manifest's `c2pa.ai_generated` then says whether it does rather
than always yes. Without `export` the file and manifest are as before.
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
GENERATOR = "Voltage"
AI_VOICE = "contains AI-generated voice"
# The container keys (mp4 `mdta`, written with use_metadata_tags so ffprobe reads them back).
TAG_EXPORT_ID, TAG_GENERATOR, TAG_CREATED, TAG_AI_VOICE = ("voltage_export_id", "voltage_generator", "voltage_created",
                                                           "voltage_ai_voice")


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


def tag(path: Path, tags: dict[str, str], ffmpeg: str = "ffmpeg") -> None:
    """Write `tags` into the file's container metadata in place, keeping what is there (the mark)."""
    tmp = path.with_name(path.stem + ".tags" + path.suffix)
    args = [a for k, v in tags.items() for a in ("-metadata", f"{k}={v}")]
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy", "-map_metadata", "0", *args,
                    "-movflags", "+faststart+use_metadata_tags", str(tmp)], check=True, capture_output=True, timeout=120)
    shutil.move(str(tmp), str(path))


def read_tags(path: Path, ffprobe: str = "ffprobe") -> dict:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60)
    try:
        return dict(json.loads(out.stdout or "{}").get("format", {}).get("tags", {}) or {})
    except ValueError:
        return {}


def export_tags(export: dict) -> dict[str, str]:
    """The permanent metadata an export carries: its id, Voltage, when, and the AI voice line when it has one."""
    tags = {TAG_EXPORT_ID: export["export_id"], TAG_GENERATOR: GENERATOR, TAG_CREATED: export["created"]}
    if export.get("ai_voice"):
        tags[TAG_AI_VOICE] = AI_VOICE
    return tags


def stamp(path: Path, *, video_id: str, owner: str, watermarker: Watermarker, signer: C2PASigner,
          source_sha: str | None = None, export: dict | None = None) -> dict:
    """Mark `path` in place and write its manifest beside it. Returns
    {"mark", "manifest": path, "sha256"} (the sha of the marked file).
    `export` ({export_id, ai_voice, label_on}, step 7): the permanent metadata too."""
    mark = secrets.token_hex(8)
    tmp = path.with_name(path.stem + ".wm" + path.suffix)
    watermarker.embed(path, tmp, mark)
    shutil.move(str(tmp), str(path))
    if export is not None:
        export = {**export, "created": export.get("created") or now_iso()}
        tag(path, export_tags(export), getattr(watermarker, "ffmpeg", "ffmpeg"))
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
    if export is not None:
        manifest["created"] = export["created"]
        manifest["assertions"][1] = {"label": "c2pa.ai_generated", "data": {"synthetic_voice": bool(export.get("ai_voice"))}}
        manifest["assertions"].append({"label": "voltage.export", "data": {
            "export_id": export["export_id"], "generator": GENERATOR, "created": export["created"],
            "ai_voice": AI_VOICE if export.get("ai_voice") else None, "label_on": bool(export.get("label_on"))}})
    signed = {"manifest": manifest, "signature": signer.sign(manifest)}
    manifest_path(path).write_text(json.dumps(signed, indent=2), encoding="utf-8")
    return {"mark": mark, "manifest": str(manifest_path(path)), "sha256": digest}
