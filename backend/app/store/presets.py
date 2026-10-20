"""B3: a project's export presets, and the file names they make.

    list_presets(db, project_id, by)              -> [Preset] (the three defaults on first use)
    add(db, project_id, data, by, codecs=)        -> Preset | None
    update(db, project_id, preset_id, data, by, codecs=) -> Preset | None
    remove(db, project_id, preset_id, by)         -> bool
    file_name(pattern, project=, video=, lang=, preset=, version=) -> "Diwali_bhaji-cam_en_Reels-9-16_v3.mp4"

First use: the first read of a project's presets writes YouTube 16:9, Reels
9:16 and Feed 1:1 (H.264, -14 LUFS, no captions) and remembers it did, so a
user who deletes them all is not given them back. Bad data is a PresetError
with a sentence fit to show. Every change writes its F7 event in its own
transaction.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass

from app.store import events
from app.store.actors import user
from app.store.db import Database
from app.timefmt import now_iso

PLATFORMS = ("youtube", "reels", "feed")
CODECS = ("h264", "hevc")
LOUDNESS = (-14.0, -16.0, -24.0)
TOKENS = ("project", "video", "lang", "preset", "version")
DEFAULT_PATTERN = "{project}_{video}_{lang}_{preset}_v{version}"
DEFAULTS = (("YouTube 16:9", "youtube"), ("Reels 9:16", "reels"), ("Feed 1:1", "feed"))
SEEDED = "export_presets_seeded:{}"
MAX_NAME = 60
MAX_PATTERN = 120
MAX_FILE = 150


class PresetError(ValueError):
    pass


@dataclass(frozen=True)
class Preset:
    preset_id: int
    project_id: str
    name: str
    platform: str
    codec: str
    loudness: float
    captions: bool
    pattern: str
    position: int
    created_by: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _preset(row) -> Preset:
    return Preset(row["id"], row["project_id"], row["name"], row["platform"], row["codec"], float(row["loudness"]),
                  bool(row["captions"]), row["pattern"], row["position"], row["created_by"], row["created_at"], row["updated_at"])


def check_pattern(pattern: str) -> str:
    """The pattern, trimmed; PresetError for an unknown token or one with no {video}."""
    pattern = " ".join(str(pattern or "").split())
    if not pattern:
        raise PresetError("A file name pattern is needed, like " + DEFAULT_PATTERN + ".")
    if len(pattern) > MAX_PATTERN:
        raise PresetError(f"A file name pattern is at most {MAX_PATTERN} characters.")
    unknown = [t for t in re.findall(r"\{([^{}]*)\}", pattern) if t not in TOKENS]
    if unknown or pattern.count("{") != pattern.count("}"):
        raise PresetError("A pattern can use " + ", ".join("{" + t + "}" for t in TOKENS) + ".")
    if "{video}" not in pattern:
        raise PresetError("Put {video} in the pattern, so every video gets its own file.")
    return pattern


def clean(data: dict, now: Preset | None = None, codecs: tuple[str, ...] | list[str] = CODECS) -> dict:
    """The preset's fields over `now` (all of them for a new one), each checked."""
    base = now.to_dict() if now else {"codec": "h264", "loudness": -14.0, "captions": False, "pattern": DEFAULT_PATTERN}
    merged = {**base, **{k: v for k, v in (data or {}).items() if v is not None}}
    name = " ".join(str(merged.get("name") or "").split())[:MAX_NAME]
    if not name:
        raise PresetError("Give the preset a name.")
    platform = merged.get("platform")
    if platform not in PLATFORMS:
        raise PresetError("A preset's platform is YouTube 16:9, Reels 9:16 or Feed 1:1.")
    codec = merged.get("codec")
    if codec not in CODECS:
        raise PresetError("A preset's codec is H.264 or HEVC.")
    if codec not in codecs:
        raise PresetError("This server cannot write HEVC. Pick H.264.")
    try:
        loud = float(merged.get("loudness"))
    except (TypeError, ValueError):
        loud = 0.0
    if loud not in LOUDNESS:
        raise PresetError("Loudness is -14 LUFS (web), -16 LUFS (general) or -24 LUFS (broadcast).")
    return {"name": name, "platform": platform, "codec": codec, "loudness": loud,
            "captions": bool(merged.get("captions")), "pattern": check_pattern(merged.get("pattern") or "")}


def _slug(value: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9]+", "-", value)).strip("-")


def file_name(pattern: str, *, project: str, video: str, lang: str, preset: str, version: int | str) -> str:
    """A file name from a pattern: each token's value made safe for any disk
    (letters, digits and hyphens), the pattern's own characters kept where
    safe, and `.mp4` on the end."""
    values = {"project": _slug(project), "video": _slug(re.sub(r"\.[A-Za-z0-9]{2,4}$", "", video)),
              "lang": _slug(lang), "preset": _slug(preset), "version": _slug(str(version))}
    parts = re.split(r"(\{[a-z]+\})", pattern)
    out = "".join(values.get(p[1:-1], "") if p.startswith("{") else re.sub(r"[^A-Za-z0-9_.-]+", "-", p) for p in parts)
    out = re.sub(r"([_.-])[_.-]+", r"\1", out).strip("_.-") or "video"
    return out[:MAX_FILE - 4] + ".mp4"


def _event(c: sqlite3.Connection, verb: str, preset: Preset, by: str, before: dict | None = None) -> None:
    payload = {"preset_id": preset.preset_id, "name": preset.name, "platform": preset.platform}
    if before is not None:
        payload["before"] = before
    events.record(c, verb, user(by), project_id=preset.project_id, target=f"preset{preset.preset_id}", payload=payload)


def _insert(c: sqlite3.Connection, project_id: str, fields: dict, by: str) -> Preset | None:
    project = c.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        return None
    position = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM export_presets WHERE project_id = ?", (project_id,)).fetchone()[0]
    at = now_iso()
    c.execute("INSERT INTO export_presets (project_id, name, platform, codec, loudness, captions, pattern, position, "
              "created_by, created_at, updated_at, workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (project_id, fields["name"], fields["platform"], fields["codec"], fields["loudness"], int(fields["captions"]),
               fields["pattern"], position, by, at, at, project["workspace_id"]))
    return get_in(c, project_id, c.execute("SELECT last_insert_rowid()").fetchone()[0])


def get_in(c: sqlite3.Connection, project_id: str, preset_id: int) -> Preset | None:
    row = c.execute("SELECT * FROM export_presets WHERE id = ? AND project_id = ?", (preset_id, project_id)).fetchone()
    return _preset(row) if row else None


def get(db: Database, project_id: str, preset_id: int) -> Preset | None:
    with db.tx() as c:
        return get_in(c, project_id, preset_id)


def list_presets(db: Database, project_id: str, by: str, seed: bool = True) -> list[Preset]:
    """The project's presets in order; the first read writes the defaults."""
    with db.tx() as c:
        if seed and c.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            key = SEEDED.format(project_id)
            if c.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone() is None:
                c.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, now_iso()))
                if c.execute("SELECT 1 FROM export_presets WHERE project_id = ?", (project_id,)).fetchone() is None:
                    for name, platform in DEFAULTS:
                        _insert(c, project_id, clean({"name": name, "platform": platform}), by)
        rows = c.execute("SELECT * FROM export_presets WHERE project_id = ? ORDER BY position, id", (project_id,)).fetchall()
    return [_preset(r) for r in rows]


def add(db: Database, project_id: str, data: dict, by: str, codecs: tuple[str, ...] | list[str] = CODECS) -> Preset | None:
    fields = clean(data, codecs=codecs)
    with db.tx() as c:
        preset = _insert(c, project_id, fields, by)
        if preset is not None:
            _event(c, "export_preset.added", preset, by)
        return preset


def update(db: Database, project_id: str, preset_id: int, data: dict, by: str,
           codecs: tuple[str, ...] | list[str] = CODECS) -> Preset | None:
    with db.tx() as c:
        now = get_in(c, project_id, preset_id)
        if now is None:
            return None
        fields = clean(data, now, codecs=codecs)
        before = {k: getattr(now, k) for k in fields}
        if fields == before:
            return now
        c.execute("UPDATE export_presets SET name = ?, platform = ?, codec = ?, loudness = ?, captions = ?, pattern = ?, "
                  "updated_at = ? WHERE id = ? AND project_id = ?",
                  (fields["name"], fields["platform"], fields["codec"], fields["loudness"], int(fields["captions"]),
                   fields["pattern"], now_iso(), preset_id, project_id))
        preset = get_in(c, project_id, preset_id)
        _event(c, "export_preset.changed", preset, by, before=before)  # type: ignore[arg-type]
        return preset


def remove(db: Database, project_id: str, preset_id: int, by: str) -> bool:
    with db.tx() as c:
        now = get_in(c, project_id, preset_id)
        if now is None:
            return False
        c.execute("DELETE FROM export_presets WHERE id = ? AND project_id = ?", (preset_id, project_id))
        _event(c, "export_preset.removed", now, by)
        return True
