"""G6: trust and safety (routes). Everything needs `golive.g6` for the owner;
the public abuse form needs it on for the deployment (the default owners).

    POST /videos/{id}/liveness                  {speaker?, fresh?}: a fresh sentence to read aloud. With
                                                `voices.cloning_verified` (run 4 item 2): a random phrase
                                                of 8 to 12 words, single use, for ten minutes; a check of
                                                this video already passed or with a reviewer comes back
                                                instead (unless `fresh`, for one with a reviewer)
    POST /videos/{id}/liveness/{attempt}        the recording (multipart `file`): checked by the
                                                LivenessProvider (fake, test mode), or with the flag by
                                                the real gate (app.safety.consent): passed | review | failed,
                                                with the reason and what to try; stored either way
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import analytics
from app.filenames import safe_filename
from app.ratelimit import RateLimit
from app.safety import consent as consent_mod, liveness as liveness_mod
from app.timefmt import iso, now_iso

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
    fresh: bool = False             # run 4 item 2: a new phrase even while one is with a reviewer


def verified_on(owner: str) -> bool:
    """Run 4 item 2: the real consent gate, for an owner with `voices.cloning_verified`."""
    return _api().flags.enabled("voices.cloning_verified", owner)


def _attempt_view(row, test_mode: bool = False) -> dict:
    return {"attempt_id": row["id"], "sentence": row["sentence"], "status": row["status"], "reason": row["reason"] or "",
            "tip": row["tip"] or "", "test_mode": test_mode, "verified": row["method"] == "verified",
            "min_seconds": consent_mod.MIN_SECONDS}


@router.post("/videos/{video_id}/liveness", status_code=201)
def start_liveness(video_id: str, req: LivenessStart | None = None, owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(video_id, owner)
    speaker = req.speaker if req else None
    if not verified_on(owner):
        attempt = "lv_" + secrets.token_hex(8)
        sentence = liveness_mod.prompt()
        with api.database.tx() as c:
            c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, created_at) "
                      "VALUES (?, ?, ?, ?, ?, 'waiting', ?, ?)",
                      (attempt, owner, video_id, speaker, sentence, api.liveness.name, now_iso()))
        return {"attempt_id": attempt, "sentence": sentence, "status": "waiting", "reason": "", "tip": "",
                "test_mode": api.liveness.test_mode, "verified": False, "min_seconds": liveness_mod.MIN_SECONDS}
    with api.database.tx() as c:
        # A check already passed, or with a reviewer, for this video: show it, rather than a new phrase.
        held = c.execute("SELECT * FROM liveness_attempts WHERE video_id = ? AND owner = ? AND method = 'verified' "
                         "AND status IN ('passed', 'review') ORDER BY created_at DESC LIMIT 1", (video_id, owner)).fetchone()
        if held is not None and not (req and req.fresh and held["status"] == "review"):
            return _attempt_view(held)
        attempt = "cv_" + secrets.token_hex(8)
        expires = iso(datetime.now(timezone.utc) + timedelta(minutes=consent_mod.ATTEMPT_MINUTES))
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, "
                  "pass_at, review_from, expires_at, created_at) VALUES (?, ?, ?, ?, ?, 'waiting', ?, 'verified', ?, ?, ?, ?)",
                  (attempt, owner, video_id, speaker, consent_mod.phrase(), api.consent_verifier.name,
                   api.consent_verifier.pass_at, api.consent_verifier.review_from, expires, now_iso()))
        row = c.execute("SELECT * FROM liveness_attempts WHERE id = ?", (attempt,)).fetchone()
    return _attempt_view(row)


@router.post("/videos/{video_id}/liveness/{attempt_id}")
async def check_liveness(video_id: str, attempt_id: str, file: UploadFile = File(...), owner: str = Depends(_owner)) -> dict:
    api = _api()
    record = api._owned(video_id, owner)
    with api.database.tx() as c:
        row = c.execute("SELECT * FROM liveness_attempts WHERE id = ? AND video_id = ? AND owner = ?",
                        (attempt_id, video_id, owner)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="That attempt is not here. Start again.")
    if row["status"] != "waiting":
        raise HTTPException(status_code=409, detail="That phrase was used already. Start again for a new one.")
    verified = row["method"] == "verified"
    if verified and row["expires_at"] and row["expires_at"] < now_iso():
        with api.database.tx() as c:
            c.execute("UPDATE liveness_attempts SET status = 'expired', checked_at = ? WHERE id = ?", (now_iso(), attempt_id))
        raise HTTPException(status_code=410, detail="That phrase has expired. Start again for a new one.")
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / safe_filename(file.filename, "liveness.webm")
        await api._spool(file, staged, "audio")
        if staged.stat().st_size > MAX_RECORDING_BYTES:
            raise HTTPException(status_code=422, detail="That recording is too long. Just the phrase is enough.")

        def check() -> tuple:           # the provider's call and the store block: off the event loop (rehearsal item 3)
            if verified:
                reference = api.consent_reference(video_id, record, row["speaker"])
                result = api.consent_verifier.verify(staged, row["sentence"], reference, video_id)
            else:
                result = api.liveness.verify(staged, row["sentence"])
            sha = None
            if staged.stat().st_size:
                container = staged.suffix.lstrip(".") or "webm"
                sha = api.artifacts.put_file(f"liveness-{owner}", staged, kind="audio", container=container, duration=0.0).sha256
            return result, sha
        result, sha = await run_in_threadpool(check)
    if not verified:
        status = "passed" if result.passed else "failed"
        with api.database.tx() as c:
            c.execute("UPDATE liveness_attempts SET status = ?, reason = ?, audio_sha = ?, checked_at = ? WHERE id = ?",
                      (status, result.reason, sha, now_iso(), attempt_id))
            analytics.track_in(c, "consent.liveness_checked", owner, {"video_id": video_id, "passed": result.passed})
        return {"attempt_id": attempt_id, "status": status, "reason": result.reason, "tip": "", "test_mode": result.test_mode,
                "verified": False}
    with api.database.tx() as c:
        c.execute("UPDATE liveness_attempts SET status = ?, reason = ?, tip = ?, audio_sha = ?, heard = ?, wer = ?, similarity = ?, "
                  "seconds = ?, rule = ?, asr_model = ?, speaker_model = ?, checked_at = ? WHERE id = ?",
                  (result.status, result.reason, result.tip, sha, result.heard, result.wer, result.similarity, result.seconds,
                   result.rule, api.consent_verifier.asr_model, api.consent_verifier.speaker_model, now_iso(), attempt_id))
        analytics.track_in(c, "consent.liveness_checked", owner, {"video_id": video_id, "passed": result.passed,
                                                                  "status": result.status, "rule": result.rule})
        if result.status == "review":
            from app.admin import admin_owner_ids
            for admin in admin_owner_ids(api.database, api.settings.admin_owners):
                api.inbox.add_in(c, admin, "consent_review", "A consent recording is waiting for review.",
                                 body=f"Video {video_id}: {result.reason}", link="#admin")
    return {"attempt_id": attempt_id, "status": result.status, "reason": result.reason, "tip": result.tip,
            "test_mode": False, "verified": True}


def passed_attempt(video_id: str, attempt_id: str | None, verified: bool = False) -> bool:
    """Whether the consent may cite this attempt: it passed (or a reviewer approved it); with
    `verified`, only an attempt of the real gate counts."""
    if not attempt_id:
        return False
    with _api().database.tx() as c:
        return c.execute("SELECT 1 FROM liveness_attempts WHERE id = ? AND video_id = ? AND status = 'passed'"
                         + (" AND method = 'verified'" if verified else ""), (attempt_id, video_id)).fetchone() is not None


def verified_consent(video_id: str) -> bool:
    """Run 4 item 2: a speaker's voice in this video may be cloned: a check of the real gate passed (or was approved)."""
    with _api().database.tx() as c:
        return c.execute("SELECT 1 FROM liveness_attempts WHERE video_id = ? AND method = 'verified' AND status = 'passed' LIMIT 1",
                         (video_id,)).fetchone() is not None


def withdraw_checks(c, video_id: str) -> None:
    """Consent withdrawn: the video's passed checks no longer count; the next consent reads a new phrase."""
    c.execute("UPDATE liveness_attempts SET status = 'withdrawn' WHERE video_id = ? AND status IN ('passed', 'review')", (video_id,))


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
    from app.admin import admin_owner_ids
    admins = admin_owner_ids(api.database, api.settings.admin_owners)     # item 10: ids, and admins named by address
    with api.database.tx() as c:
        cur = c.execute("INSERT INTO abuse_reports (location, kind, details, contact, reporter, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (req.location.strip(), req.kind, req.details.strip(), req.contact.strip(), reporter, now_iso()))
        report_id = int(cur.lastrowid)
        title = f"Abuse report #{report_id}: {ABUSE_KINDS[req.kind]}."
        analytics.track_in(c, "abuse.reported", reporter or "public", {"kind": req.kind})
        for admin in admins:
            api.inbox.add_in(c, admin, "abuse_report", title, body=req.location.strip()[:300], link="#admin")
    from app.notify import templates
    api.email_sender.send(templates.email("abuse_report", api.settings.trust_email, public_url=api.settings.public_url,
                                          title=title, location=req.location, details=req.details, contact=req.contact))
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
