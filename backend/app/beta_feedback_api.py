"""Launch rehearsal item 11: the beta feedback loop (routes).

    POST /beta-feedback                          multipart: message (required), route, video_id, job_id,
                                                 app_version, screenshot (optional PNG, JPEG or WebP,
                                                 5 MB at most, sniffed); the user agent is read from the
                                                 request. Anyone signed in, any role; 10 an hour each.
    GET  /admin/beta-feedback?status=            admins: newest first, with counts per status
    PUT  /admin/beta-feedback/{id}               admins: {status: new | seen | done} (audited)
    GET  /admin/beta-feedback/{id}/screenshot    admins: the image

A video or job id the sender cannot see is dropped (never stored as theirs).
The screenshot is kept in the artifact store under `beta-feedback/`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import admin, analytics
from app.media import sniff
from app.ratelimit import RateLimit
from app.timefmt import now_iso

router = APIRouter(tags=["beta-feedback"])
sends = RateLimit(10, 3600.0)
STORE = "beta-feedback"
MAX_MESSAGE = 4000
MAX_SCREENSHOT = 5 << 20
STATUSES = ("new", "seen", "done")
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
THANKS = "Thank you. We read every message."


def _api():
    from app.api import main
    return main


def _clip(text: str | None, n: int) -> str:
    return " ".join((text or "").split())[:n]


def _visible_video(video_id: str | None) -> str | None:
    """The video id, when the sender may open it; else nothing."""
    api = _api()
    vid = _clip(video_id, 64)
    if not vid:
        return None
    me = api.acting.get()
    record = api.repo.get(vid)
    if record is None or me is None or record.owner != me.owner:
        return None
    if me.role == "reviewer" and not api._reviewer_may_read(me, f"/videos/{vid}"):
        return None
    return vid


def _visible_job(job_id: str | None, video_id: str | None) -> str | None:
    api = _api()
    jid = _clip(job_id, 64)
    if not jid:
        return None
    job = api.activity.get(jid)
    me = api.acting.get()
    if job is None or me is None:
        return None
    if job.video_id == video_id or job.detail.get("owner") == me.owner:
        return jid
    record = api.repo.get(job.video_id)
    return jid if record is not None and record.owner == me.owner and me.role != "reviewer" else None


@router.post("/beta-feedback", status_code=201)
async def send_feedback(request: Request, message: str = Form(""), route: str = Form(""), video_id: str = Form(""),
                        job_id: str = Form(""), app_version: str = Form(""),
                        screenshot: UploadFile | None = File(None)) -> dict:
    api = _api()
    user = api.signed_in_user(request)
    if api.settings.auth_mode != "off" and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    words = (message or "").strip()[:MAX_MESSAGE]
    if not words:
        raise HTTPException(status_code=422, detail="Write a few words first.")
    if not sends.allow(user):
        raise HTTPException(status_code=429, detail="Thanks, we have your messages. Try again in an hour if there is more.")
    vid = _visible_video(video_id)
    jid = _visible_job(job_id, vid)
    sha = kind = None
    if screenshot is not None and (screenshot.filename or screenshot.size):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "shot"
            written = 0
            with staged.open("wb") as out:
                while chunk := await screenshot.read(1 << 20):
                    if not written:
                        try:
                            kind = sniff.image(chunk[:sniff.HEAD_BYTES])
                        except sniff.SniffError as exc:
                            raise HTTPException(status_code=415, detail=str(exc)) from None
                    written += len(chunk)
                    if written > MAX_SCREENSHOT:
                        raise HTTPException(status_code=413, detail="That screenshot is over 5 MB. A smaller one works.")
                    out.write(chunk)
            if written:
                sha = api.artifacts.put_file(STORE, staged, kind="image", container=kind or "png", duration=0.0).sha256
            else:
                kind = None
    me = api.acting.get()
    with api.database.tx() as c:
        cur = c.execute(
            "INSERT INTO beta_feedback (workspace_id, owner, message, route, video_id, job_id, app_version, user_agent, "
            "screenshot_sha, screenshot_type, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
            (me.workspace_id if me and me.workspace_id else None, user, words, _clip(route, 300), vid, jid,
             _clip(app_version, 80), _clip(request.headers.get("user-agent"), 400), sha, kind, now_iso()))
        fid = int(cur.lastrowid)
        if not (me and me.workspace_id):
            c.execute("UPDATE beta_feedback SET workspace_id = (SELECT id FROM workspaces WHERE owner = ? "
                      "ORDER BY created_at, id LIMIT 1) WHERE id = ?", (user, fid))
        analytics.safe_in(c, "beta_feedback.sent", user, {"screenshot": bool(sha), "route": _clip(route, 40)})
    try:                                    # beta kit: the welcome checklist's "Tell us one thing"
        from app import onboarding
        onboarding.mark(user, checklist="feedback")
    except Exception:  # noqa: BLE001 - the message is kept whatever the checklist does
        api.log.exception("onboarding mark after feedback")
    return {"id": fid, "said": THANKS}


def _row(r) -> dict:
    d = dict(r)
    d["screenshot"] = bool(d.pop("screenshot_sha", None))
    d.pop("workspace_id", None)
    return d


@router.get("/admin/beta-feedback")
def list_feedback(request: Request, status: str | None = None, limit: int = 100) -> dict:
    api = _api()
    api._admin_or_404(request)
    limit = max(1, min(limit, 200))
    with api.database.tx() as c:
        if status in STATUSES:
            rows = c.execute("SELECT * FROM beta_feedback WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM beta_feedback ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        counts = {s: 0 for s in STATUSES}
        for r in c.execute("SELECT status, COUNT(*) AS n FROM beta_feedback GROUP BY status"):
            counts[r["status"]] = r["n"]
    return {"items": [_row(r) for r in rows], "counts": counts}


class StatusChange(BaseModel):
    status: str


def _admin_writer(request: Request) -> str:
    from app.admin_api import _admin
    return _admin(request)


@router.put("/admin/beta-feedback/{feedback_id}")
def set_status(feedback_id: int, req: StatusChange, who: str = Depends(_admin_writer)) -> dict:
    api = _api()
    if req.status not in STATUSES:
        raise HTTPException(status_code=422, detail="A status is new, seen or done.")
    with api.database.tx() as c:
        row = c.execute("SELECT * FROM beta_feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No message with that number.")
        c.execute("UPDATE beta_feedback SET status = ?, status_by = ?, status_at = ? WHERE id = ?",
                  (req.status, who, now_iso(), feedback_id))
        admin.audit_in(c, who, "feedback_status", row["owner"], "", {"feedback_id": feedback_id, "from": row["status"],
                                                                      "to": req.status})
        row = c.execute("SELECT * FROM beta_feedback WHERE id = ?", (feedback_id,)).fetchone()
    return _row(row)


@router.get("/admin/beta-feedback/{feedback_id}/screenshot")
def screenshot(feedback_id: int, request: Request) -> FileResponse:
    api = _api()
    api._admin_or_404(request)
    with api.database.tx() as c:
        row = c.execute("SELECT screenshot_sha, screenshot_type FROM beta_feedback WHERE id = ?", (feedback_id,)).fetchone()
    path = api.artifacts.find(STORE, row["screenshot_sha"]) if row and row["screenshot_sha"] else None
    if path is None:
        raise HTTPException(status_code=404, detail="That message has no screenshot.")
    return FileResponse(path, media_type=IMAGE_TYPES.get(row["screenshot_type"] or "", "application/octet-stream"),
                        headers={"Cache-Control": "private, no-store", "Content-Disposition": f"inline; filename=feedback-{feedback_id}.{row['screenshot_type']}"})
