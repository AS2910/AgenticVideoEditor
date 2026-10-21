"""What an uploaded file really is, from its first bytes (launch item 2).

A file's name and the browser's content type are the uploader's word; these
checks read the bytes. Each kind of upload accepts a short list of formats
and refuses the rest with a sentence fit to show the user.

    video(head)      -> "mp4" | "mov" | "webm" | "mkv" | "avi"
    audio(head)      -> "wav" | "mp3" | "m4a" | "ogg" | "webm" | "flac" | "aac" (or a video container)
    document(head, name) -> "txt" | "md" | "json" | "csv" | "pdf" | "docx"
"""
from __future__ import annotations

from pathlib import Path

HEAD_BYTES = 4096

VIDEO_HELP = "Upload an MP4, MOV, WebM, MKV or AVI video."
AUDIO_HELP = "Upload a WAV, MP3, M4A, OGG, FLAC or WebM recording (a video with sound works too)."
DOCUMENT_HELP = "Upload a text, Markdown, CSV, JSON, PDF or Word (.docx) file."
TEXT_KINDS = ("txt", "md", "json", "csv")


class SniffError(ValueError):
    """The bytes are not a format this upload accepts; the message says what is."""


def _iso_bmff(head: bytes) -> str | None:
    """MP4, MOV and M4A all start with a box whose type is `ftyp` (or a MOV with `moov`/`wide`/`mdat` first)."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand.startswith(b"qt"):
            return "mov"
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        return "mp4"
    if len(head) >= 8 and head[4:8] in (b"moov", b"wide", b"mdat", b"free"):
        return "mov"
    return None


def _ebml(head: bytes) -> str | None:
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    return None


def video(head: bytes) -> str:
    found = _iso_bmff(head) or _ebml(head)
    if found is None and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        found = "avi"
    if found is None or found == "m4a":
        raise SniffError(f"That file is not a video we can take. {VIDEO_HELP}")
    return found


def audio(head: bytes) -> str:
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and head[1] & 0x06):
        return "mp3"
    if len(head) > 1 and head[0] == 0xFF and head[1] in (0xF1, 0xF9):
        return "aac"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    found = _iso_bmff(head) or _ebml(head)
    if found is not None:
        return found
    raise SniffError(f"That file is not a recording we can take. {AUDIO_HELP}")


def document(head: bytes, name: str) -> str:
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        if Path(name).suffix.lower() == ".docx":
            return "docx"
        raise SniffError(f"That file is a zip archive. {DOCUMENT_HELP}")
    kind = Path(name).suffix.lstrip(".").lower()
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(head) - 4:       # a multibyte character cut at the end of the head is fine
                raise SniffError(f"That file is not readable text. {DOCUMENT_HELP}") from None
        return kind if kind in TEXT_KINDS else "txt"
    raise SniffError(f"That file is not a document we can take. {DOCUMENT_HELP}")


def head_of(path: str | Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(HEAD_BYTES)
