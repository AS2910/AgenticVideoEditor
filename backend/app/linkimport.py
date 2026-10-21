"""G1: upload from a link.

A pasted share link becomes a file on disk, then an ordinary upload (the
same probe, transcription and consent rules as a dropped file). Each place a
link can come from is a `LinkImporter`: it recognises its links and turns a
share link into one that downloads the file itself.

- Google Drive: a file shared with "anyone with the link" (`/file/d/<id>`,
  `open?id=<id>`, `uc?id=<id>`), fetched through Drive's download address
  with the large-file confirmation already given.
- Dropbox: a public link (`/s/...`, `/scl/fi/...`), with `dl=1` so Dropbox
  sends the file rather than its preview page.
- YouTube (a video you own): behind the interface but off. Proving the
  video is yours needs Google OAuth with the YouTube scope (SETUP_NEEDED.md);
  until then it says so in a sentence.

`download` streams with a size cap (2 GB), sniffs what arrived (a web page
or a file that is not a video is refused with a sentence), and reports
progress. The HTTP client is injected, so tests never touch the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

import httpx

MAX_LINK_BYTES = 2 * 1024 ** 3          # 2 GB
CHUNK = 1 << 20
SNIFF_BYTES = 64
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".ts")


class ImportRefused(ValueError):
    """A link that cannot be imported; the message is the sentence the user sees."""


@dataclass(frozen=True)
class Resolved:
    provider: str          # "drive" | "dropbox" | "youtube"
    label: str             # "Google Drive"
    url: str               # where the file itself downloads from
    filename: str | None = None


class LinkImporter(Protocol):
    name: str
    label: str
    enabled: bool
    why_off: str | None

    def matches(self, host: str) -> bool: ...

    def resolve(self, url: str) -> Resolved: ...


class GoogleDrive:
    name, label, enabled, why_off = "drive", "Google Drive", True, None
    _ID = re.compile(r"/file/d/([A-Za-z0-9_-]{10,})")

    def matches(self, host: str) -> bool:
        return host in ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")

    def resolve(self, url: str) -> Resolved:
        parts = urlparse(url)
        found = self._ID.search(parts.path)
        file_id = found.group(1) if found else (parse_qs(parts.query).get("id") or [None])[0]
        if not file_id or not re.fullmatch(r"[A-Za-z0-9_-]{10,}", file_id):
            raise ImportRefused("That Google Drive link does not point at a file. Open the file in Drive, choose Share, "
                                "set it to anyone with the link, and copy that link.")
        return Resolved(self.name, self.label,
                        f"https://drive.usercontent.google.com/download?id={quote(file_id)}&export=download&confirm=t")


class Dropbox:
    name, label, enabled, why_off = "dropbox", "Dropbox", True, None

    def matches(self, host: str) -> bool:
        return host in ("dropbox.com", "www.dropbox.com", "dl.dropboxusercontent.com")

    def resolve(self, url: str) -> Resolved:
        parts = urlparse(url)
        if not (parts.path.startswith(("/s/", "/scl/fi/")) or parts.netloc == "dl.dropboxusercontent.com"):
            raise ImportRefused("That Dropbox link does not point at a file. In Dropbox choose Share, then Copy link, "
                                "and paste that link.")
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        query["dl"] = "1"
        name = unquote(parts.path.rsplit("/", 1)[-1]) or None
        return Resolved(self.name, self.label, urlunparse(parts._replace(query=urlencode(query))), name)


class YouTubeOwned:
    """Off until Google OAuth with the YouTube scope is set up: Voltage only
    imports a YouTube video it can prove belongs to the person importing it."""
    name, label, enabled = "youtube", "YouTube", False
    why_off = ("Importing from YouTube needs you to connect your Google account so Voltage can check the video is "
               "yours. That is not set up yet. Download it from YouTube Studio and upload the file instead.")

    def matches(self, host: str) -> bool:
        return host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "studio.youtube.com")

    def resolve(self, url: str) -> Resolved:
        raise ImportRefused(self.why_off)


IMPORTERS: tuple[LinkImporter, ...] = (GoogleDrive(), Dropbox(), YouTubeOwned())
NOT_A_LINK = "Paste a share link from Google Drive or Dropbox."


def importer_for(url: str) -> LinkImporter:
    parts = urlparse(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ImportRefused(NOT_A_LINK)
    host = parts.hostname or ""
    for imp in IMPORTERS:
        if imp.matches(host):
            return imp
    raise ImportRefused(f"Voltage cannot import from {host} yet. {NOT_A_LINK}")


def resolve(url: str) -> Resolved:
    imp = importer_for(url)
    if not imp.enabled:
        raise ImportRefused(imp.why_off or "That kind of link is not available yet.")
    return imp.resolve(url.strip())


def sniff(head: bytes) -> str | None:
    """The container the first bytes say, or None when it is not a video Voltage reads."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov" if head[8:10] == b"qt" else "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head else "mkv"
    if head.startswith(b"RIFF") and head[8:11] == b"AVI":
        return "avi"
    return None


def looks_like_a_page(head: bytes) -> bool:
    start = head.lstrip()[:15].lower()
    return start.startswith((b"<!doctype", b"<html", b"<?xml", b"{"))


def _filename(response: httpx.Response, fallback: str | None) -> str | None:
    cd = response.headers.get("content-disposition", "")
    star = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.I)
    if star:
        return Path(unquote(star.group(1).strip().strip('"'))).name or fallback
    plain = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if plain:
        return Path(plain.group(1).strip()).name or fallback
    return fallback


def size_words(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{max(1, round(n / 1024 ** 2))} MB"


def download(resolved: Resolved, dest_dir: Path, *, client: httpx.Client, cap: int = MAX_LINK_BYTES,
             on_progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Fetch the file into `dest_dir` and return its path. Refused with a
    sentence: a link that needs signing in, a web page instead of a file,
    anything over the cap, anything that is not a video."""
    where = resolved.label
    try:
        with client.stream("GET", resolved.url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as response:
            if response.status_code in (401, 403):
                raise ImportRefused(f"{where} would not share that file. Set it to anyone with the link and try again.")
            if response.status_code == 404:
                raise ImportRefused(f"{where} says that file does not exist. Check the link.")
            if response.status_code >= 400:
                raise ImportRefused(f"{where} refused the download ({response.status_code}). Try again in a moment.")
            total = response.headers.get("content-length")
            size = int(total) if total and total.isdigit() else None
            if size is not None and size > cap:
                raise ImportRefused(f"That file is {size_words(size)}. The limit for a link is {size_words(cap)}.")
            kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if kind in ("text/html", "application/json", "text/plain"):
                raise ImportRefused(f"That link opens a page on {where}, not a video file. Make sure the file is shared "
                                    "with anyone who has the link.")
            name = _filename(response, resolved.filename) or "import"
            part = dest_dir / "download.part"
            got, head = 0, b""
            with part.open("wb") as out:
                for chunk in response.iter_bytes(CHUNK):
                    if len(head) < SNIFF_BYTES:
                        head = (head + chunk)[:SNIFF_BYTES]
                    got += len(chunk)
                    if got > cap:
                        raise ImportRefused(f"That file is larger than {size_words(cap)}, the limit for a link.")
                    out.write(chunk)
                    if on_progress:
                        on_progress(got, size)
    except httpx.HTTPError:
        raise ImportRefused(f"Could not reach {where}. Check your connection and try again.") from None
    if got == 0:
        raise ImportRefused(f"{where} sent an empty file. Check the link.")
    container = sniff(head)
    if container is None:
        if looks_like_a_page(head):
            raise ImportRefused(f"That link opens a page on {where}, not a video file. Make sure the file is shared "
                                "with anyone who has the link.")
        raise ImportRefused("That file is not a video Voltage can read. Use an MP4, MOV, WebM or MKV.")
    stem = Path(name).stem if Path(name).suffix.lower() in VIDEO_SUFFIXES else Path(name).name
    final = dest_dir / f"{(stem or 'import')[:80]}.{container}"
    part.rename(final)
    return final
