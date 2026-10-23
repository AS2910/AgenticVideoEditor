"""Room on the data disk (rehearsal item 4, the disk drill).

Uploads and renders write the most. Past AVE_DISK_FULL_PCT used (default 95)
or under 1 GB free, new uploads and renders are refused with one sentence
(507) instead of failing halfway with "No space left on device"; reading,
playing and downloading what exists keep working. They open again on their
own once space is freed.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from app.errors import NonRetryableError

log = logging.getLogger("voltage.disk")
MIN_FREE_BYTES = 1 << 30
SHORT = ("Voltage is short of storage space right now, so new uploads and renders are paused. "
         "Your videos are safe. Try again in a little while.")


class DiskFull(NonRetryableError):
    def __init__(self) -> None:
        super().__init__(SHORT)


def full_pct() -> float:
    try:
        return float(os.environ.get("AVE_DISK_FULL_PCT") or 95)
    except ValueError:
        return 95.0


def room(path: Path) -> dict:
    u = shutil.disk_usage(path)
    return {"used_pct": round(100.0 * (u.total - u.free) / u.total, 1) if u.total else 0.0, "free_bytes": u.free}


def check(path: Path) -> None:
    """Raise DiskFull when the disk under `path` is too full for new work."""
    try:
        r = room(path)
    except OSError:
        return
    if r["used_pct"] >= full_pct() or r["free_bytes"] < MIN_FREE_BYTES:
        log.warning("disk short: %.1f%% used, %d bytes free under %s; refusing new uploads and renders",
                    r["used_pct"], r["free_bytes"], path)
        raise DiskFull()
