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

SSRF (launch item 5): only Drive and Dropbox links are accepted, but a
redirect could point anywhere, so `download` follows redirects itself (at
most `MAX_REDIRECTS`), checks every hop's address (`check_url`: http(s) on
ports 80/443, no metadata or internal names, no literal private address), and
the real client (`safe_client`) resolves each host once at connect time,
refuses it when any address is not public (`check_ip`: private, CGNAT,
loopback, link-local, unique-local, IPv4-mapped/6to4/Teredo of those,
multicast, reserved, 0.0.0.0) and connects to the address it checked, so a
DNS answer that changes between the check and the connect (rebinding) has
nothing to change. TLS still verifies the original host name (SNI and the
certificate come from the URL, not the socket). No proxies from the
environment: a proxy would connect for us and skip the check.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

import httpcore
import httpx

from app.filenames import safe_filename

MAX_LINK_BYTES = 2 * 1024 ** 3          # 2 GB
CHUNK = 1 << 20
SNIFF_BYTES = 64
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".ts")
MAX_REDIRECTS = 5
ALLOWED_PORTS = (80, 443)
# Names that reach cloud metadata or the machine itself whatever DNS says.
BLOCKED_NAMES = ("localhost", "metadata", "metadata.google.internal", "metadata.goog", "instance-data",
                 "instance-data.ec2.internal", "metadata.azure.com", "kubernetes.default", "kubernetes.default.svc")
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".svc",
                    ".cluster.local")
# Tests swap this for a fake DNS; the real one is the system resolver.
resolver: Callable[..., list] = socket.getaddrinfo


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


BLOCKED = "Voltage only downloads from public addresses. That link points somewhere it cannot go."
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str) -> None:
    """Refuse any address that is not plainly public (raises ImportRefused)."""
    ip = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    if isinstance(ip, ipaddress.IPv6Address):
        # An IPv6 form of an IPv4 address is judged as that IPv4 address.
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is None and ip.packed[:12] == bytes(12) and int(ip) > 1:   # ::a.b.c.d (IPv4-compatible)
            inner = ipaddress.IPv4Address(ip.packed[12:])
        if inner is None and ip.packed[:12] == bytes.fromhex("0064ff9b0000000000000000"):  # NAT64 64:ff9b::/96
            inner = ipaddress.IPv4Address(ip.packed[12:])
        if inner is not None:
            check_ip(inner)
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified or not ip.is_global
            or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)
            or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)):
        raise ImportRefused(BLOCKED)


def check_url(url: str) -> None:
    """Refuse a download address before any connection: not http(s), an odd
    port, credentials in it, a metadata or internal name, or a literal
    address that is not public. Names are resolved and checked at connect
    time (`safe_client`)."""
    try:
        parts = httpx.URL(url)
    except Exception:  # noqa: BLE001 - an address httpx cannot read is refused
        raise ImportRefused(BLOCKED) from None
    if parts.scheme not in ("http", "https") or not parts.host:
        raise ImportRefused(BLOCKED)
    if parts.userinfo:
        raise ImportRefused(BLOCKED)
    if (parts.port or (443 if parts.scheme == "https" else 80)) not in ALLOWED_PORTS:
        raise ImportRefused(BLOCKED)
    host = parts.host.rstrip(".").lower()
    if host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIXES) or "." not in host.strip("[]") and ":" not in host:
        raise ImportRefused(BLOCKED)
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    check_ip(literal)


def resolve_public(host: str, port: int) -> str:
    """Resolve `host` once and return one address to connect to, refusing
    when any answer is not public (one bad answer is enough to refuse: a
    rebinding name often mixes a public and a private one)."""
    name = host.strip("[]").rstrip(".").lower()
    if name in BLOCKED_NAMES or name.endswith(BLOCKED_SUFFIXES):
        raise ImportRefused(BLOCKED)
    try:
        answers = resolver(name, port, 0, socket.SOCK_STREAM)
    except OSError:
        raise httpcore.ConnectError(f"could not resolve {name}") from None
    ips = [ipaddress.ip_address(a[4][0].split("%", 1)[0]) for a in answers]
    if not ips:
        raise httpcore.ConnectError(f"could not resolve {name}")
    for ip in ips:
        check_ip(ip)
    return str(ips[0])


class _GuardedBackend(httpcore.SyncBackend):
    """Resolve, check, then connect to the checked address (not the name)."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in ALLOWED_PORTS:
            raise ImportRefused(BLOCKED)
        return super().connect_tcp(resolve_public(host, port), port, timeout=timeout,
                                   local_address=local_address, socket_options=socket_options)

    def connect_unix_socket(self, *args, **kwargs):  # pragma: no cover - never for a link
        raise ImportRefused(BLOCKED)


def safe_client() -> httpx.Client:
    """The real client for link downloads: checked connects, no env proxies,
    no automatic redirects (`download` follows and checks each one)."""
    transport = httpx.HTTPTransport(retries=0)
    transport._pool._network_backend = _GuardedBackend()  # httpcore 1.x: read when each connection opens
    return httpx.Client(transport=transport, trust_env=False, follow_redirects=False)


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
        return safe_filename(unquote(star.group(1).strip().strip('"')), fallback or "import")
    plain = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if plain:
        return safe_filename(plain.group(1).strip(), fallback or "import")
    return fallback


def size_words(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{max(1, round(n / 1024 ** 2))} MB"


class _Follow:
    """`client.stream` that follows redirects itself, checking every hop."""

    def __init__(self, client: httpx.Client, url: str) -> None:
        self.client, self.url, self._cm = client, url, None

    def __enter__(self) -> httpx.Response:
        url = self.url
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            cm = self.client.stream("GET", url, follow_redirects=False, timeout=httpx.Timeout(30.0, read=120.0))
            response = cm.__enter__()
            if response.is_redirect and response.headers.get("location"):
                nxt = str(response.url.join(response.headers["location"]))
                cm.__exit__(None, None, None)
                url = nxt
                continue
            self._cm = cm
            return response
        raise ImportRefused("That link redirects too many times. Copy the share link again and paste it.")

    def __exit__(self, *exc) -> None:
        if self._cm is not None:
            self._cm.__exit__(*exc)


def _open(client: httpx.Client, url: str) -> _Follow:
    return _Follow(client, url)


def download(resolved: Resolved, dest_dir: Path, *, client: httpx.Client, cap: int = MAX_LINK_BYTES,
             on_progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Fetch the file into `dest_dir` and return its path. Refused with a
    sentence: a link that needs signing in, a web page instead of a file,
    anything over the cap, anything that is not a video."""
    where = resolved.label
    try:
        with _open(client, resolved.url) as response:
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
