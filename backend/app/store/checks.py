"""The project check's records (A2): each run, the issues it found, and the
fingerprints the user ignored.

    start(db, project_id, mode, trigger, by, job_id=None) -> check id
    finish(db, check_id, issues, cost_usd=0, notes=())   -> stores the issues, marks it done
    fail(db, check_id, error)
    latest(db, project_id)                               -> dict | None (the newest run)
    issues(db, check_id)                                 -> [dict], each with `ignored`
    ignore(db, project_id, fingerprint, by) / ignored(db, project_id) -> set

An issue's fingerprint is its kind and key with the text it was found in,
hashed (app.agent.project_check), so an ignored issue stays ignored until
that text changes: a changed line is a new fingerprint, and it shows again.
"""
from __future__ import annotations

import json

from app.store.db import Database
from app.store.workspaces import stamp_last
from app.timefmt import now_iso


def start(db: Database, project_id: str, mode: str, trigger: str, by: str, job_id: str | None = None) -> int:
    with db.tx() as c:
        cur = c.execute("INSERT INTO project_checks (project_id, mode, status, job_id, trigger, created_by, started_at) "
                        "VALUES (?, ?, 'running', ?, ?, ?, ?)", (project_id, mode, job_id, trigger, by, now_iso()))
        stamp_last(c, "project_checks", "", project_id)
        return int(cur.lastrowid)


def set_job(db: Database, check_id: int, job_id: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE project_checks SET job_id = ? WHERE id = ?", (job_id, check_id))


def finish(db: Database, check_id: int, issues: list[dict], cost_usd: float = 0.0, notes: tuple[str, ...] | list[str] = ()) -> None:
    with db.tx() as c:
        row = c.execute("SELECT project_id FROM project_checks WHERE id = ?", (check_id,)).fetchone()
        if row is None:
            return
        for issue in issues:
            c.execute("INSERT INTO project_issues (check_id, project_id, kind, message, places, fingerprint) VALUES (?, ?, ?, ?, ?, ?)",
                      (check_id, row["project_id"], issue["kind"], issue["message"], json.dumps(issue["places"]), issue["fingerprint"]))
            stamp_last(c, "project_issues", "", row["project_id"])
        c.execute("UPDATE project_checks SET status = 'done', cost_usd = ?, notes = ?, finished_at = ? WHERE id = ?",
                  (round(float(cost_usd), 6), json.dumps(list(notes)), now_iso(), check_id))


def fail(db: Database, check_id: int, error: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE project_checks SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                  (error[:300], now_iso(), check_id))


def _check(row) -> dict:
    return {"check_id": row["id"], "project_id": row["project_id"], "mode": row["mode"], "status": row["status"],
            "job_id": row["job_id"], "trigger": row["trigger"], "cost_usd": round(float(row["cost_usd"]), 6),
            "notes": json.loads(row["notes"] or "[]"), "error": row["error"], "created_by": row["created_by"],
            "started_at": row["started_at"], "finished_at": row["finished_at"]}


def get(db: Database, check_id: int) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_checks WHERE id = ?", (check_id,)).fetchone()
    return _check(row) if row else None


def latest(db: Database, project_id: str, finished: bool = False) -> dict | None:
    """The newest run (with `finished`, the newest that ended)."""
    with db.tx() as c:
        row = c.execute("SELECT * FROM project_checks WHERE project_id = ?" + (" AND status != 'running'" if finished else "")
                        + " ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    return _check(row) if row else None


def ignored(db: Database, project_id: str) -> set[str]:
    with db.tx() as c:
        rows = c.execute("SELECT fingerprint FROM project_issue_ignores WHERE project_id = ?", (project_id,)).fetchall()
    return {r[0] for r in rows}


def issues(db: Database, check_id: int) -> list[dict]:
    """The run's issues in the order found, each saying whether it is ignored now."""
    with db.tx() as c:
        rows = c.execute("SELECT * FROM project_issues WHERE check_id = ? ORDER BY id", (check_id,)).fetchall()
    if not rows:
        return []
    gone = ignored(db, rows[0]["project_id"])
    return [{"issue_id": r["id"], "kind": r["kind"], "message": r["message"], "places": json.loads(r["places"]),
             "fingerprint": r["fingerprint"], "ignored": r["fingerprint"] in gone} for r in rows]


def issue(db: Database, project_id: str, issue_id: int) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT check_id FROM project_issues WHERE id = ? AND project_id = ?", (issue_id, project_id)).fetchone()
    if row is None:
        return None
    return next((i for i in issues(db, row["check_id"]) if i["issue_id"] == issue_id), None)


def ignore(db: Database, project_id: str, fingerprint: str, by: str) -> None:
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO project_issue_ignores (project_id, fingerprint, ignored_by, ignored_at) VALUES (?, ?, ?, ?)",
                  (project_id, fingerprint, by, now_iso()))
        c.execute("UPDATE project_issue_ignores SET workspace_id = (SELECT workspace_id FROM projects WHERE id = ?) "
                  "WHERE project_id = ? AND fingerprint = ?", (project_id, project_id, fingerprint))
