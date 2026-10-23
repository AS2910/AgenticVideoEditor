"""Launch item 5: one rule for a file name that came from outside (an
upload's filename, a Content-Disposition header, a video's name reused for
an export or a zip entry).

The result is a bare name: no directory part in either slash style, no
drive letter, no leading dots (so never `.` or `..` and never hidden), no
control characters, none of the characters Windows refuses, at most 200
characters. Joining it to a directory stays in that directory, and a zip
entry made from it unpacks where the person unzips it, on any system.
"""
from __future__ import annotations

import re
import unicodedata

MAX_NAME = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_WINDOWS = re.compile(r'[<>:"|?*]')


def safe_filename(name: str | None, fallback: str = "file") -> str:
    text = unicodedata.normalize("NFC", str(name or ""))
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = _CONTROL.sub("", text)
    text = _WINDOWS.sub("-", text).strip().lstrip(". ").rstrip(". ")
    if len(text) > MAX_NAME:
        stem, dot, ext = text.rpartition(".")
        text = (stem[: MAX_NAME - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else text[:MAX_NAME]
    return text or fallback


def unique_names(names: list[str], fallback: str = "file") -> list[str]:
    """Each name made safe, a second copy of one named `name-2.ext` and so on
    (two entries with one name in a zip overwrite each other when unpacked)."""
    seen: set[str] = set()
    out = []
    for raw in names:
        name = safe_filename(raw, fallback)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        n, candidate = 2, name
        while candidate.lower() in seen:
            candidate = f"{stem}-{n}.{ext}" if ext else f"{stem}-{n}"
            n += 1
        seen.add(candidate.lower())
        out.append(candidate)
    return out
