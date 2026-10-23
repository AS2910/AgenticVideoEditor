"""G6: trust and safety (routes). Everything needs `golive.g6` for the owner;
the public abuse form needs it on for the deployment (the default owners).

    POST /videos/{id}/liveness                  {speaker?}: a fresh sentence to read aloud
    POST /videos/{id}/liveness/{attempt}        the recording (multipart `file`): checked by the
                                                LivenessProvider (fake, test mode), stored either way
    POST /videos/{id}/consent/withdraw          consent withdrawn now: the speaker's clones are
                                                deleted at the voice service at once
    POST /abuse-reports                         public, no account, rate limited: stored, and the
                                                admins are told (bell and email)
    POST /me/data-export                        a zip of your data, as an Activity job
    GET  /me/data-export                        your exports and deletion requests
    GET  /me/data-export/{job_id}/download      the zip
    GET  /exports/provenance/{mark}             what an export's mark says (owner only)
"""
from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import analytics
from app.ratelimit import RateLimit
from app.safety import liveness as liveness_mod
from app.timefmt import now_iso

router = APIRouter(tags=["safety"])
abuse_limit = RateLimit(5, 3600.0)
ABUSE_KINDS = {"impersonation": "Someone's voice used without their consent",
               "public_figure": "A public figure's voice",
               "misleading": "Misleading or deceptive content",
               "hateful": "Hateful, harassing or violent content",
               "other": "Something else"}
MAX_RECORDING_BYTES = 10 << 20


def _api():
    from app.api import main
    return main


def _owner(request: Request) -> str:
    owner = _api().current_owner(request)
    if not _api().flags.enabled("golive.g6", owner):
        raise HTTPException(status_code=404, detail="Not found")
    return owner


def deployment_on() -> bool:
    api = _api()
    return any(api.flags.enabled("golive.g6", o) for o in api.settings.flag_owners)


# ── liveness ─────────────────────────────────────────────────────────────────

class LivenessStart(BaseModel):
    speaker: str | None = None


@router.post("/videos/{video_id}/liveness", status_code=201)
def start_liveness(video_id: str, req: LivenessStart | None = None, owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(video_id, owner)
    attempt = "lv_" + secrets.token_hex(8)
    sentence = liveness_mod.prompt()
    with api.database.tx() as c:
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, created_at) "
                  "VALUES (?, ?, ?, ?, ?, 'waiting', ?, ?)",
                  (attempt, owner, video_id, (req.speaker if req else None), sentence, api.liveness.name, now_iso()))
    return {"attempt_id": attempt, "sentence": sentence, "test_mode": api.liveness.test_mode}


@router.post("/videos/{video_id}/liveness/{attempt_id}")
async def check_liveness(video_id: str, attempt_id: str, file: UploadFile = File(...), owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(video_id, owner)
    with api.database.tx() as c:
        row = c.execute("SELECT * FROM liveness_attempts WHERE id = ? AND video_id = ? AND owner = ?",
                        (attempt_id, video_id, owner)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="That attempt is not here. Start again.")
    if row["status"] != "waiting":
        raise HTTPException(status_code=409, detail="That sentence was used already. Start again for a new one.")
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / Path(file.filename or "liveness.webm").name
        await api._spool(file, staged, "audio")
        if staged.stat().st_size > MAX_RECORDING_BYTES:
            raise HTTPException(status_code=422, detail="That recording is too long. Just the sentence is enough.")

        def check() -> tuple:           # the provider's call and the store block: off the event loop (rehearsal item 3)
            result = api.liveness.verify(staged, row["sentence"])
            sha = None
            if staged.stat().st_size:
                container = staged.suffix.lstrip(".") or "webm"
                sha = api.artifacts.put_file(f"liveness-{owner}", staged, kind="audio", container=container, duration=0.0).sha256
            return result, sha
        result, sha = await run_in_threadpool(check)
    status = "passed" if result.passed else "failed"
    with api.database.tx() as c:
        c.execute("UPDATE liveness_attempts SET status = ?, reason = ?, audio_sha = ?, checked_at = ? WHERE id = ?",
                  (status, result.reason, sha, now_iso(), attempt_id))
        analytics.track_in(c, "consent.liveness_checked", owner, {"video_id": video_id, "passed": result.passed})
    return {"attempt_id": attempt_id, "status": status, "reason": result.reason, "test_mode": result.test_mode}


def passed_attempt(video_id: str, attempt_id: str | None) -> bool:
    if not attempt_id:
        return False
    with _api().database.tx() as c:
        return c.execute("SELECT 1 FROM liveness_attempts WHERE id = ? AND video_id = ? AND status = 'passed'",
                         (attempt_id, video_id)).fetchone() is not None


# ── withdraw consent now ─────────────────────────────────────────────────────

@router.post("/videos/{video_id}/consent/withdraw")
def withdraw_consent(video_id: str, owner: str = Depends(_owner)) -> dict:
    return _api().withdraw_consent_now(video_id, owner)


# ── abuse reports ────────────────────────────────────────────────────────────

class AbuseReport(BaseModel):
    location: str = Field(min_length=1, max_length=1000)
    kind: str
    details: str = Field(default="", max_length=4000)
    contact: str = Field(default="", max_length=200)


@router.get("/abuse-reports/open")
def abuse_form_open() -> dict:
    """Public: whether the abuse form takes reports here (the share page and Help ask)."""
    return {"open": deployment_on(), "kinds": [{"kind": k, "label": v} for k, v in ABUSE_KINDS.items()]}


@router.post("/abuse-reports", status_code=201)
def report_abuse(req: AbuseReport, request: Request) -> dict:
    api = _api()
    if not deployment_on():
        raise HTTPException(status_code=404, detail="Not found")
    if req.kind not in ABUSE_KINDS:
        raise HTTPException(status_code=422, detail="Pick what is wrong.")
    who = request.client.host if request.client else "unknown"
    if not abuse_limit.allow(who):
        raise HTTPException(status_code=429, detail="Thanks, we have your reports. Try again in an hour if there is more.")
    try:
        reporter = api.signed_in_user(request) if api.settings.auth_mode != "off" else None
    except HTTPException:
        reporter = None
    with api.database.tx() as c:
        cur = c.execute("INSERT INTO abuse_reports (location, kind, details, contact, reporter, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (req.location.strip(), req.kind, req.details.strip(), req.contact.strip(), reporter, now_iso()))
        report_id = int(cur.lastrowid)
        title = f"Abuse report #{report_id}: {ABUSE_KINDS[req.kind]}."
        analytics.track_in(c, "abuse.reported", reporter or "public", {"kind": req.kind})
        for admin in api.settings.admin_owners:
            api.inbox.add_in(c, admin, "abuse_report", title, body=req.location.strip()[:300], link="#admin")
    api.email_sender.send(api.email_mod.Email(to=api.settings.trust_email, subject=title, kind="abuse_report",
                                              body=f"{title}\nWhere: {req.location}\nDetails: {req.details or '(none)'}\n"
                                                   f"Contact: {req.contact or '(none)'}"))
    return {"report_id": report_id, "said": "Thank you. We read every report and act on it."}


def recent_reports(limit: int = 20) -> list[dict]:
    with _api().database.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM abuse_reports ORDER BY id DESC LIMIT ?", (limit,))]


# ── your data ────────────────────────────────────────────────────────────────

@router.post("/me/data-export", status_code=202)
def start_export(owner: str = Depends(_owner)) -> dict:
    return _api().start_data_export(owner)


@router.get("/me/data-export")
def list_exports(owner: str = Depends(_owner)) -> dict:
    api = _api()
    with api.database.tx() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM data_requests WHERE owner = ? ORDER BY id DESC LIMIT 20", (owner,))]
    for r in rows:
        job = api.activity.get(r["job_id"]) if r.get("job_id") else None
        r["job"] = job.to_dict() if job else None
    return {"requests": rows}


@router.get("/me/data-export/{job_id}/download")
def download_export(job_id: str, request: Request, mt: str | None = None) -> FileResponse:
    owner = _api().media_owner(request, mt)   # launch item 2: a signed, expiring URL
    api = _api()
    job = api.activity.get(job_id)
    if job is None or job.kind != "data_export" or job.detail.get("owner") != owner or job.status != "done":
        raise HTTPException(status_code=404, detail="That export is not ready or not yours.")
    path = api.data_export_path(owner, job_id)
    if not path.exists():
        raise HTTPException(status_code=410, detail="That export has been cleared. Make a new one.")
    return FileResponse(path, media_type="application/zip", filename=f"voltage-data-{job_id}.zip")


@router.get("/exports/provenance/{mark}")
def provenance(mark: str, owner: str = Depends(_owner)) -> dict:
    with _api().database.tx() as c:
        row = c.execute("SELECT * FROM provenance_marks WHERE mark = ? AND owner = ?", (mark, owner)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No export of yours carries that mark.")
    return {**dict(row), "manifest": json.loads(row["manifest"])}
