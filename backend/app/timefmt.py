"""One way to write a moment (bug 2, 2026-10-19).

Every time the app stores or sends is an ISO 8601 UTC string with
milliseconds and a `Z` — `2026-10-19T14:32:05.123Z` — or null. Never a
number, never a boolean. One fixed width also keeps the ledger's string
comparisons (`at >= ?`) true: mixing `+00:00` and `Z` forms would not sort.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

FORMAT = "%Y-%m-%dT%H:%M:%S"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
CANON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def iso(moment: datetime) -> str:
    """A datetime as the canonical string (naive times are taken as UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime(FORMAT) + f".{moment.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))


def to_iso(value: Any) -> str | None:
    """Anything a time was ever stored as, in the canonical form — or None
    when it is not a time at all (None, booleans, zero, garbage). Numbers are
    epoch seconds, or milliseconds when they are too large to be seconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        seconds = value / 1000 if value > 1e11 else value
        return iso(datetime.fromtimestamp(seconds, tz=timezone.utc))
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, str):
        text = value.strip()
        if not _ISO.match(text):
            return None
        try:
            return iso(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def is_time_key(key: str) -> bool:
    """The keys that hold a moment, in the database's JSON and on the wire."""
    return key == "at" or key.endswith("_at")


# Subtrees whose `at` is a position in the clip, in seconds — not a moment.
CLIP_TIME = frozenset({"frames", "inserts", "beats", "manifest", "pieces", "segments", "layers", "words"})


def normalise(obj: Any) -> tuple[Any, int]:
    """Every moment in a JSON value rewritten to the canonical form. Returns
    the value and how many were changed. A value under a time key that is not
    a time becomes None. Clip-time subtrees (`CLIP_TIME`) are left alone."""
    changed = 0
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in CLIP_TIME:
                out[k] = v
            elif is_time_key(k) and not isinstance(v, (dict, list)):
                new = to_iso(v)
                if new != v:
                    changed += 1
                out[k] = new
            else:
                out[k], n = normalise(v)
                changed += n
        return out, changed
    if isinstance(obj, list):
        out_list = []
        for v in obj:
            nv, n = normalise(v)
            out_list.append(nv)
            changed += n
        return out_list, changed
    return obj, 0
