"""D2: learned style. Every decision on a line Voltage proposed is logged
(added, rejected, or edited before adding, with the text difference and the
reason when one was given); after every 10 decisions in a project, one
Claude pass may suggest ONE line for the brief or a style rule. A suggestion
changes nothing until it is accepted; what was accepted is listed as "What
Voltage has learned", and removing an item takes it back out (a new brief
version without that line, or the rule removed), so the next turn's opening
view no longer has it.

    record_in(c, decision=..., ...)           -> (decision id, decisions in the project)
    due(count)                                -> a pass is due at 10, 20, 30...
    decisions(db, project_id, limit)          -> newest first
    reason(db, decision_id, owner, text)      -> the reason, given after the fact
    suggest(db, project_id, kind, text, why, at_count) -> the pending suggestion (one at a time)
    pending(db, project_id) / learned(db, project_id)
    accept(db, project_id, item_id, by) / dismiss(...) / remove(...)

Bad input is a LearnedError with a sentence fit to show. Every change to the
brief or rules goes through their own services (F2/F3) and writes its F7
event in the same transaction.
"""
from __future__ import annotations

import json
import sqlite3

from app.store import briefs, events, rules
from app.store.actors import VOLTAGE, user
from app.store.db import Database
from app.timefmt import now_iso

DECISIONS = ("added", "rejected", "edited")
KINDS = ("brief", "rule")
EVERY = 10
MAX_REASON = 300
MAX_TEXT = 300
REASONS = ("Wrong words", "Wrong voice", "Too long", "Not needed")


class LearnedError(ValueError):
    pass


def due(count: int) -> bool:
    """A pattern pass runs after every 10th decision in a project, and only then."""
    return count > 0 and count % EVERY == 0


def _decision(row) -> dict:
    return {"decision_id": row["id"], "project_id": row["project_id"], "video_id": row["video_id"],
            "plan_id": row["plan_id"], "item_id": row["item_id"], "decision": row["decision"],
            "reason": row["reason"], "proposed_text": row["proposed_text"], "final_text": row["final_text"],
            "diff": json.loads(row["diff"] or "[]"), "by": row["by"], "at": row["at"]}


def record_in(c: sqlite3.Connection, *, video_id: str, decision: str, proposed_text: str, final_text: str | None = None,
              plan_id: str | None = None, item_id: str | None = None, reason: str | None = None,
              by: str) -> tuple[int, int]:
    """Log one decision on a proposal; returns its id and how many decisions
    its project now holds (0 for a standalone video: no pattern pass)."""
    if decision not in DECISIONS:
        raise LearnedError(f"A decision is one of: {', '.join(DECISIONS)}.")
    row = c.execute("SELECT project_id, workspace_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    project_id = row["project_id"] if row else None
    diff = briefs.diff_text(proposed_text or "", final_text or "") if decision == "edited" else []
    cur = c.execute(
        "INSERT INTO proposal_decisions (workspace_id, project_id, video_id, plan_id, item_id, decision, reason, "
        "proposed_text, final_text, diff, by, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["workspace_id"] if row else None, project_id, video_id, plan_id, item_id, decision,
         (reason or "").strip()[:MAX_REASON] or None, proposed_text or "", final_text, json.dumps(diff), by, now_iso()))
    count = c.execute("SELECT COUNT(*) FROM proposal_decisions WHERE project_id = ?", (project_id,)).fetchone()[0] if project_id else 0
    return int(cur.lastrowid), int(count)


def reason(db: Database, decision_id: int, video_id: str, text: str) -> dict | None:
    """The reason for a decision, given after it (Discard, then Why?)."""
    said = " ".join((text or "").split())[:MAX_REASON]
    if not said:
        raise LearnedError("Say why in a few words.")
    with db.tx() as c:
        row = c.execute("SELECT * FROM proposal_decisions WHERE id = ? AND video_id = ?", (decision_id, video_id)).fetchone()
        if row is None:
            return None
        c.execute("UPDATE proposal_decisions SET reason = ? WHERE id = ?", (said, decision_id))
        return _decision(c.execute("SELECT * FROM proposal_decisions WHERE id = ?", (decision_id,)).fetchone())


def decisions(db: Database, project_id: str, limit: int = 30) -> list[dict]:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM proposal_decisions WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                         (project_id, limit)).fetchall()
    return [_decision(r) for r in rows]


def count(db: Database, project_id: str) -> int:
    with db.tx() as c:
        return int(c.execute("SELECT COUNT(*) FROM proposal_decisions WHERE project_id = ?", (project_id,)).fetchone()[0])


# ── suggestions and what was learned ──

def _item(row) -> dict:
    return {"item_id": row["id"], "project_id": row["project_id"], "kind": row["kind"], "text": row["text"],
            "why": row["why"], "status": row["status"], "rule_id": row["rule_id"], "brief_version": row["brief_version"],
            "at_count": row["at_count"], "created_at": row["created_at"], "decided_at": row["decided_at"],
            "decided_by": row["decided_by"]}


def _get_in(c: sqlite3.Connection, project_id: str, item_id: int):
    return c.execute("SELECT * FROM learned_items WHERE id = ? AND project_id = ?", (item_id, project_id)).fetchone()


def _event(c: sqlite3.Connection, verb: str, row, actor, **payload) -> None:
    events.record(c, verb, actor, project_id=row["project_id"], target=f"learned{row['id']}",
                  payload={"kind": row["kind"], "text": row["text"], **payload})


def suggest(db: Database, project_id: str, kind: str, text: str, why: str, at_count: int) -> dict:
    """Voltage's one suggestion from a pass. A newer one takes the place of a
    suggestion still waiting (it saw more decisions). Nothing else changes."""
    if kind not in KINDS:
        raise LearnedError("A suggestion is for the brief or a rule.")
    line = " ".join((text or "").split())[:MAX_TEXT]
    if not line:
        raise LearnedError("A suggestion needs its line.")
    with db.tx() as c:
        project = c.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise LearnedError("That project is gone.")
        c.execute("UPDATE learned_items SET status = 'replaced', decided_at = ? WHERE project_id = ? AND status = 'suggested'",
                  (now_iso(), project_id))
        cur = c.execute("INSERT INTO learned_items (workspace_id, project_id, kind, text, why, status, at_count, created_at) "
                        "VALUES (?, ?, ?, ?, ?, 'suggested', ?, ?)",
                        (project["workspace_id"], project_id, kind, line, " ".join((why or "").split())[:MAX_TEXT], at_count, now_iso()))
        row = _get_in(c, project_id, int(cur.lastrowid))
        _event(c, "learned.suggested", row, VOLTAGE, at_count=at_count)
        return _item(row)


def pending(db: Database, project_id: str) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM learned_items WHERE project_id = ? AND status = 'suggested' ORDER BY id DESC LIMIT 1",
                        (project_id,)).fetchone()
    return _item(row) if row else None


def learned(db: Database, project_id: str) -> list[dict]:
    """What Voltage has learned here: the accepted items, oldest first."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM learned_items WHERE project_id = ? AND status = 'accepted' ORDER BY id",
                         (project_id,)).fetchall()
    return [_item(r) for r in rows]


def _waiting_or_error(c: sqlite3.Connection, project_id: str, item_id: int):
    row = _get_in(c, project_id, item_id)
    if row is None or row["status"] != "suggested":
        raise LearnedError("That suggestion is not waiting any more.")
    return row


def accept(db: Database, project_id: str, item_id: int, by: str) -> dict:
    """Apply the suggestion: a brief line is a new brief version with the line
    at the end; a rule is a new style rule."""
    with db.tx() as c:
        row = _waiting_or_error(c, project_id, item_id)
        version, rule_id = None, None
        if row["kind"] == "brief":
            now = briefs.current_in(c, project_id)
            text = (now.text.rstrip() if now else "")
            saved = briefs.save_in(c, project_id, (text + "\n" + row["text"]) if text else row["text"], by)
            version = saved.version if saved else None
        else:
            rule = rules.add_in(c, project_id, "style", {"text": row["text"]}, by)
            rule_id = rule.rule_id if rule else None
        c.execute("UPDATE learned_items SET status = 'accepted', brief_version = ?, rule_id = ?, decided_at = ?, decided_by = ? "
                  "WHERE id = ?", (version, rule_id, now_iso(), by, item_id))
        row = _get_in(c, project_id, item_id)
        _event(c, "learned.accepted", row, user(by), brief_version=version, rule_id=rule_id)
        return _item(row)


def dismiss(db: Database, project_id: str, item_id: int, by: str) -> dict:
    with db.tx() as c:
        row = _waiting_or_error(c, project_id, item_id)
        c.execute("UPDATE learned_items SET status = 'dismissed', decided_at = ?, decided_by = ? WHERE id = ?",
                  (now_iso(), by, item_id))
        row = _get_in(c, project_id, item_id)
        _event(c, "learned.dismissed", row, user(by))
        return _item(row)


def _without_line(text: str, line: str) -> str:
    """The brief with every line that is exactly `line` taken out (spaces ignored)."""
    want = " ".join(line.split())
    kept = [ln for ln in text.split("\n") if " ".join(ln.split()) != want]
    return "\n".join(kept).strip()


def remove(db: Database, project_id: str, item_id: int, by: str) -> dict:
    """Take a learned item back out: a brief line goes in a new brief version
    without it (if it is still there), a rule is removed (if it still is)."""
    with db.tx() as c:
        row = _get_in(c, project_id, item_id)
        if row is None or row["status"] != "accepted":
            raise LearnedError("That is not on the learned list any more.")
        version = None
        if row["kind"] == "brief":
            now = briefs.current_in(c, project_id)
            if now is not None:
                after = _without_line(now.text, row["text"])
                if after != now.text.strip():
                    saved = briefs.save_in(c, project_id, after, by)
                    version = saved.version if saved else None
        elif row["rule_id"] is not None:
            rules.remove_in(c, project_id, int(row["rule_id"]), by)
        c.execute("UPDATE learned_items SET status = 'removed', decided_at = ?, decided_by = ? WHERE id = ?",
                  (now_iso(), by, item_id))
        row = _get_in(c, project_id, item_id)
        _event(c, "learned.removed", row, user(by), brief_version=version)
        return _item(row)


def request_text(project: dict, recent: list[dict], rule_lines: list[str]) -> str:
    """What the pass reads: the brief and rules as they stand, then the
    decisions, oldest first, each on a few plain lines."""
    out = [f"Project: {project.get('name') or 'this project'}", f"Brief: {project.get('brief') or '(none)'}",
           "Rules: " + ("; ".join(rule_lines) if rule_lines else "(none)"), "", "Decisions, oldest first:"]
    for d in reversed(recent):
        head = {"added": "Added as proposed", "rejected": "Thrown out", "edited": "Rewritten, then added"}[d["decision"]]
        line = f"- {head}: \"{d['proposed_text']}\""
        if d["decision"] == "edited" and d.get("final_text") is not None:
            line += f" became \"{d['final_text']}\""
        if d.get("reason"):
            line += f". Why: {d['reason']}"
        out.append(line)
    return "\n".join(out)
