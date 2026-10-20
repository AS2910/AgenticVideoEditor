"""D1: project templates. A template is what a project shares, kept to start
new projects from: the brief (its current text), the words and rules (F3/A3),
the export presets (B3), the defaults for new videos and the ceiling. Voices
are referenced, never copied at the vendor: a template keeps each shared
voice's entry (its id and name), and a project made from it shares them.

    snapshot_in(c, project_id, by)               -> data (what a template holds)
    save(db, owner, name, data, source)          -> Template
    list_for(db, owner)                          -> [Template] (starters first)
    get(db, owner, template_id)                  -> Template | None
    rename(db, owner, template_id, name)         -> Template | None
    remove(db, owner, template_id)               -> bool
    apply_in(c, project_id, data, by)            -> fills a new project's rules and presets

Starters: three templates written here (Festive ad, Product explainer,
Interview cleanup), the same for everyone, read-only and never deleted. Their
ids start with `starter-`. Bad input is a TemplateError with a sentence fit
to show. Every change writes its F7 event in the same transaction.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import asdict, dataclass

from app.store import events, presets, rules
from app.store.actors import user
from app.store.db import Database
from app.store.workspaces import personal
from app.timefmt import now_iso

MAX_NAME = 80
STARTER_PREFIX = "starter-"
# A rule's clip (A3's example audio) belongs to the project it was recorded
# in, so it stays behind; the words themselves travel.
_PROJECT_ONLY_RULE_FIELDS = ("audio",)
_PRESET_FIELDS = ("name", "platform", "codec", "loudness", "captions", "pattern")


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Template:
    template_id: str
    name: str
    starter: bool
    data: dict
    owner: str | None = None
    source_project_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out["summary"] = summary(self.data)
        return out


def summary(data: dict) -> dict:
    """What the template carries, counted, for its row in a list."""
    rules_ = data.get("rules") or []
    return {"brief": (data.get("brief") or "")[:160], "rules": len(rules_),
            "words": sum(1 for r in rules_ if r.get("kind") == "pronounce"),
            "presets": len(data.get("presets") or []), "voices": len(data.get("voices") or []),
            "ceiling_usd": data.get("ceiling_usd"), "settings": data.get("settings") or {}}


def clean_name(name: str) -> str:
    label = " ".join(str(name or "").split())[:MAX_NAME]
    if not label:
        raise TemplateError("Give the template a name.")
    return label


# ── the three starters ──

def _preset(name: str, platform: str, captions: bool = False, loudness: float = -14.0) -> dict:
    return {"name": name, "platform": platform, "codec": "h264", "loudness": loudness, "captions": captions,
            "pattern": presets.DEFAULT_PATTERN}


STARTERS: tuple[Template, ...] = (
    Template(
        template_id="starter-festive-ad", name="Festive ad", starter=True,
        description="A short sale or offer ad for a festival, in several cuts.",
        data={
            "brief": ("A short festive ad for a sale or an offer. Warm, upbeat and clear. Say the offer, the price "
                      "and the last date the same way in every video. Keep each line short enough to fit its gap. "
                      "End with what to do next, like visiting the store or the website."),
            "rules": [
                {"kind": "required_line", "data": {"text": "T&C apply."}},
                {"kind": "banned", "data": {"word": "guaranteed"}},
                {"kind": "style", "data": {"text": "Say prices in full, with the currency, the same way every time."}},
            ],
            "presets": [_preset("Reels 9:16", "reels", captions=True), _preset("Feed 1:1", "feed", captions=True),
                        _preset("YouTube 16:9", "youtube")],
            "settings": {"autonomy": "ask", "turn_usd": 0.5, "effort": "medium"},
            "ceiling_usd": 20.0, "voices": [],
        }),
    Template(
        template_id="starter-product-explainer", name="Product explainer", starter=True,
        description="One product, explained plainly, for the web and social.",
        data={
            "brief": ("A clear explainer for one product. Plain words, one idea per line, a calm and confident voice. "
                      "Name the product the same way every time. Say what it does, who it is for and how to start."),
            "rules": [
                {"kind": "style", "data": {"text": "Use plain words. Explain a technical term the first time it is said."}},
                {"kind": "style", "data": {"text": "One idea per line."}},
            ],
            "presets": [_preset("YouTube 16:9", "youtube", captions=True), _preset("Feed 1:1", "feed", captions=True)],
            "settings": {"autonomy": "ask", "turn_usd": 0.5, "effort": "medium"},
            "ceiling_usd": 15.0, "voices": [],
        }),
    Template(
        template_id="starter-interview-cleanup", name="Interview cleanup", starter=True,
        description="A recorded interview or talk, tidied without changing what was meant.",
        data={
            "brief": ("A recorded interview or talk. Keep the speaker's own words and voice. Fix slips, repeated words "
                      "and long pauses; never change what the speaker means. Ask before rewording anything they said."),
            "rules": [
                {"kind": "style", "data": {"text": "Keep the speaker's meaning. Only fix slips, repeats and filler words."}},
                {"kind": "style", "data": {"text": "Use the speaker's own voice for every fixed line."}},
            ],
            "presets": [_preset("YouTube 16:9", "youtube", captions=True, loudness=-16.0)],
            "settings": {"autonomy": "ask", "turn_usd": 0.3, "effort": "medium"},
            "ceiling_usd": 10.0, "voices": [],
        }),
)


def starter(template_id: str) -> Template | None:
    return next((t for t in STARTERS if t.template_id == template_id), None)


# ── what a project holds ──

def snapshot_in(c: sqlite3.Connection, project_id: str, by: str) -> dict | None:
    """What a template made from the project carries now (voices are added by
    the caller, which knows whose they are). None when there is no project."""
    row = c.execute("SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)).fetchone()
    if row is None:
        return None
    from app.store import briefs
    brief = briefs.current_in(c, project_id)
    kept = []
    for r in rules.list_in(c, project_id):
        kept.append({"kind": r.kind, "data": {k: v for k, v in r.data.items() if k not in _PROJECT_ONLY_RULE_FIELDS}})
    found = c.execute("SELECT * FROM export_presets WHERE project_id = ? ORDER BY position, id", (project_id,)).fetchall()
    if not found and c.execute("SELECT 1 FROM meta WHERE key = ?", (presets.SEEDED.format(project_id),)).fetchone() is None:
        # Never opened: the project would show the three defaults, so the template carries them.
        kept_presets = [presets.clean({"name": n, "platform": p}) for n, p in presets.DEFAULTS]
    else:
        kept_presets = [{k: (bool(p[k]) if k == "captions" else p[k]) for k in _PRESET_FIELDS} for p in found]
    return {"brief": brief.text if brief else (row["brief"] or ""), "rules": kept, "presets": kept_presets,
            "settings": json.loads(row["settings"] or "{}"), "ceiling_usd": row["ceiling_usd"], "voices": []}


def apply_in(c: sqlite3.Connection, project_id: str, data: dict, by: str) -> None:
    """Give a new project the template's rules and presets (the brief,
    defaults and ceiling go in with the project row; voices with the caller)."""
    for r in data.get("rules") or []:
        try:
            rules.add_in(c, project_id, r["kind"], r["data"], by)
        except (rules.RuleError, KeyError):
            continue   # a rule this version cannot read is left out, never a failed project
    c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (presets.SEEDED.format(project_id), now_iso()))
    for p in data.get("presets") or []:
        try:
            fields = presets.clean(p)
        except presets.PresetError:
            continue
        made = presets._insert(c, project_id, fields, by)
        if made is not None:
            presets._event(c, "export_preset.added", made, by)


# ── the owner's templates ──

def _template(row) -> Template:
    return Template(template_id=row["id"], name=row["name"], starter=False, data=json.loads(row["data"] or "{}"),
                    owner=row["owner"], source_project_id=row["source_project_id"], created_at=row["created_at"],
                    updated_at=row["updated_at"])


def _event(c: sqlite3.Connection, verb: str, t: Template, by: str, workspace_id: str | None, **payload) -> None:
    events.record(c, verb, user(by), project_id=t.source_project_id if verb == "template.saved" else None,
                  target=t.template_id, payload={"name": t.name, **payload}, workspace_id=workspace_id)


def save(db: Database, owner: str, name: str, data: dict, source_project_id: str | None = None) -> Template:
    label = clean_name(name)
    at = now_iso()
    template_id = "t" + secrets.token_hex(5)
    with db.tx() as c:
        ws = personal(c, owner)
        c.execute("INSERT INTO project_templates (id, owner, workspace_id, name, data, source_project_id, created_by, "
                  "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (template_id, owner, ws, label, json.dumps(data), source_project_id, owner, at, at))
        t = _template(c.execute("SELECT * FROM project_templates WHERE id = ?", (template_id,)).fetchone())
        _event(c, "template.saved", t, owner, ws, **summary(data))
    return t


def list_for(db: Database, owner: str) -> list[Template]:
    """The starters, then the owner's own templates, newest first."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM project_templates WHERE owner = ? ORDER BY created_at DESC, rowid DESC", (owner,)).fetchall()
    return [*STARTERS, *(_template(r) for r in rows)]


def get(db: Database, owner: str, template_id: str) -> Template | None:
    found = starter(template_id)
    if found is not None:
        return found
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_templates WHERE id = ? AND owner = ?", (template_id, owner)).fetchone()
    return _template(row) if row else None


def rename(db: Database, owner: str, template_id: str, name: str) -> Template | None:
    if starter(template_id):
        raise TemplateError("Starter templates cannot be renamed. Make a project from it and save that as your own.")
    label = clean_name(name)
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_templates WHERE id = ? AND owner = ?", (template_id, owner)).fetchone()
        if row is None:
            return None
        before = row["name"]
        if before == label:
            return _template(row)
        c.execute("UPDATE project_templates SET name = ?, updated_at = ? WHERE id = ?", (label, now_iso(), template_id))
        t = _template(c.execute("SELECT * FROM project_templates WHERE id = ?", (template_id,)).fetchone())
        _event(c, "template.renamed", t, owner, row["workspace_id"], before=before)
    return t


def remove(db: Database, owner: str, template_id: str) -> bool:
    if starter(template_id):
        raise TemplateError("Starter templates cannot be deleted.")
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_templates WHERE id = ? AND owner = ?", (template_id, owner)).fetchone()
        if row is None:
            return False
        c.execute("DELETE FROM project_templates WHERE id = ?", (template_id,))
        _event(c, "template.deleted", _template(row), owner, row["workspace_id"])
    return True


def purge_owner_in(c: sqlite3.Connection, owner: str) -> None:
    """Account deletion takes the owner's templates."""
    c.execute("DELETE FROM project_templates WHERE owner = ?", (owner,))
