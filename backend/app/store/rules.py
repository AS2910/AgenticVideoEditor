"""The project's rules (F3): how to say a term, words never said, lines
every video carries, style rules. Read into every turn's opening view.

    add(db, project_id, kind, data, by)         -> Rule
    update(db, project_id, rule_id, data, by)   -> Rule | None (version + 1)
    remove(db, project_id, rule_id, by)         -> bool
    get(db, project_id, rule_id) / list_rules(db, project_id, kind=None)
    rules_version(db, project_id)               -> int (+1 on every change)

Each write has an `_in(c, ...)` form on a transaction the caller holds, so
every change writes its activity event (F7) in the same transaction. A bad `data` raises
RuleError with a sentence fit to show.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from app.store import events
from app.store.actors import user
from app.store.db import Database
from app.timefmt import now_iso

KINDS = ("pronounce", "banned", "required_line", "style")
# What each kind holds: its required text fields, then its optional ones.
FIELDS = {
    # A3: `audio` is the sha256 of an optional short clip of the right pronunciation.
    "pronounce": (("term", "say"), ("respell", "audio")),
    "banned": (("word",), ()),
    "required_line": (("text",), ()),
    "style": (("text",), ()),
}
MAX_TEXT = 500


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    rule_id: int
    project_id: str
    kind: str
    data: dict
    version: int
    created_by: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _rule(row) -> Rule:
    return Rule(row["id"], row["project_id"], row["kind"], json.loads(row["data"]), row["version"],
                row["created_by"], row["updated_at"])


def clean(kind: str, data: dict) -> dict:
    """The rule's fields, trimmed; RuleError when the kind is unknown or a
    required field is missing."""
    if kind not in KINDS:
        raise RuleError(f"A rule is one of: {', '.join(KINDS)}.")
    if not isinstance(data, dict):
        raise RuleError("A rule's data is an object.")
    required, optional = FIELDS[kind]
    out: dict = {}
    for key in required + optional:
        value = data.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split())[:MAX_TEXT]
        if text:
            out[key] = text
    missing = [k for k in required if k not in out]
    if missing:
        raise RuleError(f"A {kind.replace('_', ' ')} rule needs {' and '.join(missing)}.")
    return out


def _bump(c: sqlite3.Connection, project_id: str) -> None:
    c.execute("UPDATE projects SET rules_version = rules_version + 1 WHERE id = ?", (project_id,))


def add_in(c: sqlite3.Connection, project_id: str, kind: str, data: dict, by: str) -> Rule | None:
    """None when there is no such project."""
    data = clean(kind, data)
    project = c.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        return None
    c.execute("INSERT INTO project_rules (project_id, kind, data, version, created_by, updated_at, workspace_id) "
              "VALUES (?, ?, ?, 1, ?, ?, ?)", (project_id, kind, json.dumps(data), by, now_iso(), project["workspace_id"]))
    rule_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    _bump(c, project_id)
    rule = get_in(c, project_id, rule_id)
    _event(c, "rule.added", rule, by)
    return rule


def update_in(c: sqlite3.Connection, project_id: str, rule_id: int, data: dict, by: str) -> Rule | None:
    """Replace the rule's data (same kind); its version goes up by one. The
    same data again changes nothing. None when there is no such rule."""
    now = get_in(c, project_id, rule_id)
    if now is None:
        return None
    data = clean(now.kind, data)
    if data == now.data:
        return now
    c.execute("UPDATE project_rules SET data = ?, version = version + 1, updated_at = ? WHERE id = ? AND project_id = ?",
              (json.dumps(data), now_iso(), rule_id, project_id))
    _bump(c, project_id)
    rule = get_in(c, project_id, rule_id)
    _event(c, "rule.changed", rule, by, before=now.data)
    return rule


def remove_in(c: sqlite3.Connection, project_id: str, rule_id: int, by: str = "") -> bool:
    rule = get_in(c, project_id, rule_id)
    if rule is None:
        return False
    c.execute("DELETE FROM project_rules WHERE id = ? AND project_id = ?", (rule_id, project_id))
    _bump(c, project_id)
    _event(c, "rule.removed", rule, by)
    return True


def _event(c: sqlite3.Connection, verb: str, rule: Rule, by: str, before: dict | None = None) -> None:
    """The activity log's line for a rule change (F7), in the same transaction."""
    payload = {"rule_id": rule.rule_id, "kind": rule.kind, "data": rule.data, "version": rule.version}
    if before is not None:
        payload["before"] = before
    events.record(c, verb, user(by), project_id=rule.project_id, target=f"rule{rule.rule_id}", payload=payload)


def get_in(c: sqlite3.Connection, project_id: str, rule_id: int) -> Rule | None:
    row = c.execute("SELECT * FROM project_rules WHERE id = ? AND project_id = ?", (rule_id, project_id)).fetchone()
    return _rule(row) if row else None


def list_in(c: sqlite3.Connection, project_id: str, kind: str | None = None) -> list[Rule]:
    rows = c.execute("SELECT * FROM project_rules WHERE project_id = ?" + (" AND kind = ?" if kind else "")
                     + " ORDER BY id", (project_id, kind) if kind else (project_id,)).fetchall()
    return [_rule(r) for r in rows]


def add(db: Database, project_id: str, kind: str, data: dict, by: str) -> Rule | None:
    with db.tx() as c:
        return add_in(c, project_id, kind, data, by)


def update(db: Database, project_id: str, rule_id: int, data: dict, by: str) -> Rule | None:
    with db.tx() as c:
        return update_in(c, project_id, rule_id, data, by)


def remove(db: Database, project_id: str, rule_id: int, by: str = "") -> bool:
    with db.tx() as c:
        return remove_in(c, project_id, rule_id, by)


def get(db: Database, project_id: str, rule_id: int) -> Rule | None:
    with db.tx() as c:
        return get_in(c, project_id, rule_id)


def list_rules(db: Database, project_id: str, kind: str | None = None) -> list[Rule]:
    """The project's rules in the order they were made, all kinds or one."""
    with db.tx() as c:
        return list_in(c, project_id, kind)


def rules_version(db: Database, project_id: str) -> int:
    with db.tx() as c:
        row = c.execute("SELECT rules_version FROM projects WHERE id = ?", (project_id,)).fetchone()
    return int(row[0]) if row else 0
