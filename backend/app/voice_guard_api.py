"""Voice consent V1, step 2: the voice guard's routes (app.safety.voice_guard).
Everything but the admin routes needs `voices.cloning_verified` for the owner
(404 when off, as if none of it were here).

    GET  /voices/attestation/statement          the attestation's words and version (and the export reminder's)
    POST /videos/{id}/voices/{voice}/attest     {choice: my_voice | have_permission, statement_version}: the
                                                user's word on whose voice it is; `voice` is a voice id, or a
                                                speaker's label before their clone is made (the
                                                attestation_required error names which)
    POST /exports/{export_ref}/confirm          {label_on}: the export reminder confirmed for what the
                                                export_confirm_required error listed (one for a whole batch)
    GET  /voices/scopes                         the owner's voice records: scope, status, source video
    POST /voices/{id}/promote                   Save to My voices: library after a passed own-voice check
                                                (own_voice_check_required without one), kept in My voices
    POST /voices/{id}/withdraw                  withdrawn now, deleted at the vendor (queued if it fails)
    POST /admin/users/{owner}/suspend-cloning   {reason}: no new clones, every cloned voice disabled (audited)
    POST /admin/users/{owner}/restore-cloning   {reason}: the voices the suspension disabled come back (audited;
                                                step 7: the reason is required)
    POST /admin/users/{owner}/clone-limits      {day, month, reason}: raise a person's clone limits (audited)
    GET  /admin/users/{owner}/cloning           step 7: suspended or not, the limits and use, cloned voices by status
    GET  /admin/exports/{ref}/trace             step 7: Trace: the voices, attestations, export confirmation,
                                                synthesis log and line checks behind an export, and the user;
                                                `ref` is an export id, a provenance mark, the export reminder's
                                                reference, or an abuse report's number. Audited (it reads
                                                personal data), found or not
    GET  /admin/line-checks?verdict=review      step 4: the held lines (state waiting, oldest first; or decided)
    POST /admin/line-checks/{id}                {decision: approve | reject, reason}: never on your own line (audited;
                                                the owner is told). A line nobody checks in 48 hours is rejected.

A refusal answers `{"detail": {"code", "message", ...}}` with the error's
status (the app's VoiceGuardError handler).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import admin

router = APIRouter(tags=["voice consent"])


def _api():
    from app.api import main
    return main


def _owner(request: Request) -> str:
    api = _api()
    owner = api.current_owner(request)
    if not api.voice_guard.enabled(owner):
        raise HTTPException(status_code=404, detail="Not found")
    return owner


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@router.get("/voices/attestation/statement")
def attestation_statement(owner: str = Depends(_owner)) -> dict:
    return _api().voice_guard.statement()


class AttestRequest(BaseModel):
    choice: str
    statement_version: str


@router.post("/videos/{video_id}/voices/{voice}/attest", status_code=201)
def attest_voice(video_id: str, voice: str, req: AttestRequest, request: Request, owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(video_id, owner)
    ip, agent = _client(request)
    return api.voice_guard.attest(owner, video_id, voice, req.choice, req.statement_version, ip=ip, user_agent=agent)


class ConfirmExportRequest(BaseModel):
    label_on: bool = True


@router.post("/exports/{export_ref}/confirm", status_code=201)
def confirm_export(export_ref: str, req: ConfirmExportRequest | None = None, request: Request = None,
                   owner: str = Depends(_owner)) -> dict:
    ip, _ = _client(request) if request is not None else (None, None)
    return _api().voice_guard.confirm_export(owner, export_ref, req.label_on if req else True, ip=ip)


@router.get("/voices/scopes")
def voice_scopes(owner: str = Depends(_owner)) -> dict:
    guard = _api().voice_guard
    return {"voices": [guard.describe(r["voice_id"]) for r in guard.records_of(owner)]}


@router.post("/voices/{voice_id}/promote")
def promote_voice(voice_id: str, owner: str = Depends(_owner)) -> dict:
    api = _api()
    record = api.voice_guard.promote(owner, voice_id)
    api.keep_promoted_voice(owner, record)
    return api.voice_guard.describe(voice_id)


@router.post("/voices/{voice_id}/withdraw")
def withdraw_voice(voice_id: str, owner: str = Depends(_owner)) -> dict:
    api = _api()
    record = api.voice_guard.withdraw(owner, voice_id)
    api.forget_withdrawn_voice(record)
    return {**api.voice_guard.describe(voice_id), "vendor_state": record["vendor_state"]}


# ── admin ────────────────────────────────────────────────────────────────────

def _admin(request: Request) -> str:
    from app.admin_api import _admin as admin_only
    return admin_only(request)


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


def _reason(text: str | None) -> str:
    said = admin.clean_reason(text)
    if len(said) < 3:
        raise HTTPException(status_code=422, detail="Say why, in a few words. It goes in the audit trail.")
    return said


@router.post("/admin/users/{owner}/suspend-cloning")
def suspend_cloning(owner: str, req: ReasonRequest, who: str = Depends(_admin)) -> dict:
    api = _api()
    reason = _reason(req.reason)
    disabled = api.voice_guard.suspend(owner, reason, who)
    admin.audit(api.database, who, "voice_suspend", owner, reason, {"voices_disabled": disabled})
    return {"owner": owner, "suspended": True, "voices_disabled": disabled}


@router.post("/admin/users/{owner}/restore-cloning")
def restore_cloning(owner: str, req: ReasonRequest, who: str = Depends(_admin)) -> dict:
    api = _api()
    reason = _reason(req.reason)
    restored = api.voice_guard.restore(owner, who)
    admin.audit(api.database, who, "voice_restore", owner, reason, {"voices_restored": restored})
    return {"owner": owner, "suspended": False, "voices_restored": restored}


@router.get("/admin/users/{owner}/cloning")
def cloning_state(owner: str, who: str = Depends(_admin)) -> dict:
    return _api().voice_guard.cloning_state(owner)


class LimitsRequest(BaseModel):
    day: int = Field(ge=0, le=1000)
    month: int = Field(ge=0, le=10000)
    reason: str = Field(default="", max_length=500)


@router.post("/admin/users/{owner}/clone-limits")
def clone_limits(owner: str, req: LimitsRequest, who: str = Depends(_admin)) -> dict:
    api = _api()
    reason = _reason(req.reason)
    day, month = api.voice_guard.set_limits(owner, req.day, req.month)
    admin.audit(api.database, who, "voice_clone_limits", owner, reason, {"day": day, "month": month})
    return {"owner": owner, "day": day, "month": month}


# ── step 7: Trace ────────────────────────────────────────────────────────────

@router.get("/admin/exports/{ref}/trace")
def trace_export(ref: str, who: str = Depends(_admin)) -> dict:
    api = _api()
    ref = ref.strip()[:80]
    if len(ref) < 1:
        raise HTTPException(status_code=422, detail="Paste an export id, a mark or an abuse report number.")
    found = api.voice_guard.trace(ref)
    admin.audit(api.database, who, "voice_trace", ref, "", {
        "found": found is not None, "owners": [u["owner"] for u in (found or {}).get("users", [])],
        "marks": [e["mark"] for e in (found or {}).get("exports", [])]})
    if found is None:
        raise HTTPException(status_code=404, detail="Nothing matches that. Check the export id, mark or report number.")
    for u in found["users"]:
        u["emails"] = admin.emails_of(api.database, u["owner"])
    return found


# ── step 4: the held lines' queue ────────────────────────────────────────────

@router.get("/admin/line-checks")
def line_checks_queue(verdict: str = "review", state: str = "waiting", limit: int = 50, who: str = Depends(_admin)) -> dict:
    if verdict != "review":
        raise HTTPException(status_code=422, detail="Only held lines (verdict=review) have a queue.")
    return _api().voice_guard.review_queue("waiting" if state == "waiting" else "decided", limit)


class LineDecision(BaseModel):
    decision: str
    reason: str = Field(default="", max_length=500)


@router.post("/admin/line-checks/{check_id}")
def decide_line_check(check_id: str, req: LineDecision, who: str = Depends(_admin)) -> dict:
    api = _api()
    reason = _reason(req.reason)
    row = api.voice_guard.decide_review(check_id, who, req.decision, reason)
    admin.audit(api.database, who, "line_approve" if row["review_state"] == "approved" else "line_reject", row["owner"],
                reason, {"line_check_id": check_id, "video_id": row["video_id"], "categories": row["categories"]})
    return row
