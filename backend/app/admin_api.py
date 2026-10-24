"""Launch rehearsal item 10: admin tools for launch day (routes).

Admins only (AVE_ADMIN_OWNERS): everyone else gets 404, as if none of this
were here. Every change is written to the audit trail (`app.admin.audit`).

    GET  /admin/users?q=                          find people by address or owner id (partial)
    GET  /admin/users/{owner}                     their workspace (members, roles), spend (today, month,
                                                  all time, by vendor), credits and grants, invoices,
                                                  recent jobs, recent error reports, suspension, audit
    POST /admin/users/{owner}/grant               {credits, reason}: credits that never lapse
    POST /admin/users/{owner}/refund              {reason, invoice_id?, credits?}: an invoice refunded in full
                                                  through its provider (test mode: the fake), or a credit
                                                  reversal of `credits` when there is no payment
    POST /admin/users/{owner}/suspend             {reason}: 403 everywhere for them and their members,
                                                  running jobs cancelled, share and media links stop
    POST /admin/users/{owner}/unsuspend           {reason?}: everything back
    POST /admin/shares/{share_id}/revoke          {reason}: take a share link down (abuse)
    GET  /admin/audit?limit=&owner=               the audit trail, newest first
    GET  /admin/consent-reviews?status=           run 4 item 2: consent checks waiting for a person
                                                  (status review, or decided: passed | failed), with
                                                  the phrase, what was heard and the scores
    GET  /admin/consent-reviews/{id}/recording    the consent recording
    GET  /admin/consent-reviews/{id}/source       the speaker's speech in the video it was compared with
    POST /admin/consent-reviews/{id}              {decision: approve | reject, reason}: passed or did not
                                                  pass, audited, and the owner is told
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import admin, analytics, billing
from app.timefmt import iso, now_iso

router = APIRouter(tags=["admin"])


def _api():
    from app.api import main
    return main


def _admin(request: Request) -> str:
    """The signed-in admin, or 404. Writes also need the CSRF header."""
    api = _api()
    who = api._admin_or_404(request)
    if request.method not in ("GET", "HEAD") and api.settings.auth_mode != "off" \
            and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    return who


def _need_reason(reason: str | None) -> str:
    said = admin.clean_reason(reason)
    if len(said) < 3:
        raise HTTPException(status_code=422, detail="Say why, in a few words. It goes in the audit trail.")
    return said


def _known(owner: str) -> str:
    """The owner id, when Voltage has ever seen it (a workspace, an account or an address)."""
    owner = owner.strip()
    api = _api()
    with api.database.tx() as c:
        seen = c.execute("SELECT 1 FROM workspaces WHERE owner = ? UNION SELECT 1 FROM meta WHERE key = ? "
                         "UNION SELECT 1 FROM workspace_members WHERE member = ? LIMIT 1",
                         (owner, f"notify_email:{owner}", owner)).fetchone()
        if seen is None and owner.startswith("acct:"):
            seen = c.execute("SELECT 1 FROM accounts WHERE id = ?", (owner[5:],)).fetchone()
    if not owner or seen is None:
        raise HTTPException(status_code=404, detail="Nobody with that owner id.")
    return owner


@router.get("/admin/users")
def find_users(q: str = "", who: str = Depends(_admin)) -> dict:
    return {"q": q, "users": admin.find(_api().database, q)}


def _day_start() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00.000Z")


def _jobs(owner: str, workspace_id: str, limit: int = 20) -> list[dict]:
    from app.jobs.activity import _load
    api = _api()
    with api.database.tx() as c:
        rows = c.execute("SELECT body FROM jobs WHERE workspace_id = ? OR project_id = ? ORDER BY seq DESC LIMIT ?",
                         (workspace_id, f"user-{owner}", limit)).fetchall()
    out = []
    for r in rows:
        j = _load(r["body"])
        out.append({"job_id": j.job_id, "video_id": j.video_id, "kind": j.kind, "status": j.status,
                    "error_code": j.error_code, "error_text": j.error_text, "created_at": j.created_at,
                    "finished_at": j.finished_at, "cost_usd": j.cost_usd})
    return out


def _errors(people: list[str], limit: int = 20) -> list[dict]:
    api = _api()
    marks = ",".join("?" for _ in people)
    with api.database.tx() as c:
        rows = c.execute(f"SELECT id, owner, source, message, location, at FROM error_reports WHERE owner IN ({marks}) "
                         "ORDER BY id DESC LIMIT ?", (*people, limit)).fetchall()
    return [dict(r) for r in rows]


def user_view(owner: str) -> dict:
    api = _api()
    db = api.database
    from app.store import members as members_store
    wid = members_store.workspace_of(db, owner)
    ws = members_store.workspace(db, wid) or {}
    team = [{"member": m.member, "email": m.email, "name": m.name, "role": m.role, "joined_at": m.joined_at,
             "spend_limit_usd": m.spend_limit_usd} for m in members_store.members(db, wid)]
    joined = [w for w in members_store.workspaces_for(db, owner) if not w["own"]]
    from app.usage import month_start
    month = iso(month_start())
    spend = {
        "today_usd": round(api.ledger.spent_usd_by_owner(owner, _day_start()), 4),
        "month_usd": round(api.ledger.spent_usd_by_owner(owner, month), 4),
        "all_time_usd": round(api.ledger.spent_usd_by_owner(owner), 4),
        "by_vendor": api.ledger.by_vendor_for_owner(owner),
        "by_vendor_month": api.ledger.by_vendor_for_owner(owner, month),
    }
    credits = None
    invoices: list[dict] = []
    if billing.has_account(db, owner):
        credits = billing.credits(db, owner, lambda at: api.ledger.spent_usd_by_owner(owner, at))
        invoices = [{"id": i["id"], "number": i["number"], "description": i["description"], "total": i["total"],
                     "currency": i["currency"], "provider": i["provider"], "test_mode": i["test_mode"],
                     "issued_at": i["issued_at"], "refunded": billing.refunded(db, i["id"])}
                    for i in billing.invoices(db, owner)][:20]
    with db.tx() as c:
        acct = c.execute("SELECT created_at, verified_at, deleted_at FROM accounts WHERE id = ?",
                         (owner[5:],)).fetchone() if owner.startswith("acct:") else None
    return {
        "owner": owner, "emails": admin.emails_of(db, owner), "kind": admin._kind(owner),
        "is_admin": admin.is_admin_owner(db, owner, api.settings.admin_owners),
        "account": dict(acct) if acct else None,
        "suspended": admin.suspension(db, owner),
        "workspace": {"workspace_id": wid, "name": ws.get("name"), "members": team},
        "member_of": joined,
        "spend": spend, "credits": credits, "invoices": invoices,
        "jobs": _jobs(owner, wid),
        "errors": _errors([owner, *(m["member"] for m in team)]),
        "audit": admin.recent_audit(db, 20, target=owner),
    }


@router.get("/admin/users/{owner}")
def get_user(owner: str, who: str = Depends(_admin)) -> dict:
    return user_view(_known(owner))


class GrantRequest(BaseModel):
    credits: float = Field(gt=0, le=10_000)
    reason: str = Field(default="", max_length=500)


@router.post("/admin/users/{owner}/grant")
def grant_credits(owner: str, req: GrantRequest, who: str = Depends(_admin)) -> dict:
    owner = _known(owner)
    reason = _need_reason(req.reason)
    try:
        made = billing.admin_grant(_api().database, owner, round(req.credits, 2), reason)
    except billing.BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    admin.audit(_api().database, who, "grant", owner, reason, {"credits": made["credits"], "grant_id": made["grant_id"]})
    analytics.track("admin.granted", who, {"credits": made["credits"]})
    return user_view(owner)


class RefundRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    invoice_id: int | None = None
    credits: float | None = Field(default=None, gt=0, le=10_000)


@router.post("/admin/users/{owner}/refund")
def mark_refund(owner: str, req: RefundRequest, who: str = Depends(_admin)) -> dict:
    """A payment refunded in full through the provider that took it (credits taken
    back), or, without an invoice, a credit reversal of `credits`."""
    api = _api()
    owner = _known(owner)
    reason = _need_reason(req.reason)
    if req.invoice_id is not None:
        found = billing.invoice(api.database, owner, req.invoice_id)
        if found is None:
            raise HTTPException(status_code=404, detail="That invoice is not theirs or does not exist.")
        from app.billing.providers import provider_named
        try:
            done = billing.refund(api.database, owner, req.invoice_id, provider_named(found["provider"], api.settings))
        except billing.BillingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        admin.audit(api.database, who, "refund", owner, reason,
                    {"invoice": found["number"], "refund_id": done["refund_id"], "total": found["total"],
                     "currency": found["currency"], "credits_taken_back": done["credits_taken_back"],
                     "test_mode": found["test_mode"]})
    elif req.credits:
        try:
            made = billing.admin_grant(api.database, owner, -round(req.credits, 2), reason)
        except billing.BillingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        admin.audit(api.database, who, "refund", owner, reason, {"credit_reversal": req.credits, "grant_id": made["grant_id"]})
    else:
        raise HTTPException(status_code=422, detail="Pick a payment to refund, or the credits to take back.")
    analytics.track("admin.refunded", who, {"invoice": req.invoice_id is not None})
    return user_view(owner)


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/admin/users/{owner}/suspend")
def suspend_user(owner: str, req: ReasonRequest, who: str = Depends(_admin)) -> dict:
    api = _api()
    owner = _known(owner)
    reason = _need_reason(req.reason)
    if admin.is_admin_owner(api.database, owner, api.settings.admin_owners) or owner == who:
        raise HTTPException(status_code=422, detail="An admin cannot be suspended here. Take them off AVE_ADMIN_OWNERS first.")
    if admin.suspend(api.database, owner, reason, who):
        stopped = api.stop_work_of(owner)
        admin.audit(api.database, who, "suspend", owner, reason, {"jobs_stopped": stopped})
        api.log.warning("%s suspended by %s: %s", owner, who, reason)
    return user_view(owner)


@router.post("/admin/users/{owner}/unsuspend")
def unsuspend_user(owner: str, req: ReasonRequest | None = None, who: str = Depends(_admin)) -> dict:
    api = _api()
    owner = _known(owner)
    if admin.unsuspend(api.database, owner):
        admin.audit(api.database, who, "unsuspend", owner, (req.reason if req else "") or "", {})
        api.log.warning("%s unsuspended by %s", owner, who)
    return user_view(owner)


@router.post("/admin/shares/{share_id}/revoke")
def revoke_share(share_id: str, req: ReasonRequest, who: str = Depends(_admin)) -> dict:
    """Take a share link down (an abuse report). Paste the link or its id: the part after #s/ before the dot."""
    api = _api()
    from app.store import shares as shares_store
    sid = share_id.strip().rsplit("/", 1)[-1].split(".", 1)[0]
    reason = _need_reason(req.reason)
    share = shares_store.get(api.database, sid)
    if share is None:
        raise HTTPException(status_code=404, detail="No share link with that id.")
    done = shares_store.revoke(api.database, sid, who) or share
    admin.audit(api.database, who, "share_revoke", share.owner, reason,
                {"share_id": sid, "scope": share.scope, "target": share.target})
    return {"share_id": sid, "owner": share.owner, "state": done.state()}


@router.get("/admin/audit")
def get_audit(limit: int = 50, owner: str | None = None, who: str = Depends(_admin)) -> dict:
    return {"entries": admin.recent_audit(_api().database, limit, target=owner)}


# ── consent reviews (run 4 item 2) ──────────────────────────────────────────

REVIEW_FIELDS = ("id", "owner", "video_id", "speaker", "sentence", "status", "reason", "heard", "wer", "similarity", "seconds",
                 "rule", "asr_model", "speaker_model", "pass_at", "review_from", "created_at", "checked_at",
                 "reviewed_by", "review_reason", "reviewed_at")
APPROVED = "A person listened to the recording and approved it."
REJECTED = "A person listened to the recording and could not confirm it is the speaker in the video."


def _review_row(r) -> dict:
    return {**{k: r[k] for k in REVIEW_FIELDS}, "has_recording": bool(r["audio_sha"])}


def _attempt(attempt_id: str):
    with _api().database.tx() as c:
        row = c.execute("SELECT * FROM liveness_attempts WHERE id = ? AND method = 'verified'", (attempt_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No consent check with that id.")
    return row


@router.get("/admin/consent-reviews")
def consent_reviews(status: str = "review", limit: int = 50, who: str = Depends(_admin)) -> dict:
    """The queue (status `review`, oldest first, so the longest wait is on top), or the decided ones, newest first."""
    limit = max(1, min(int(limit), 200))
    with _api().database.tx() as c:
        if status == "review":
            rows = c.execute("SELECT * FROM liveness_attempts WHERE method = 'verified' AND status = 'review' "
                             "ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM liveness_attempts WHERE method = 'verified' AND reviewed_at IS NOT NULL "
                             "ORDER BY reviewed_at DESC LIMIT ?", (limit,)).fetchall()
        waiting = c.execute("SELECT COUNT(*) FROM liveness_attempts WHERE method = 'verified' AND status = 'review'").fetchone()[0]
    return {"items": [_review_row(r) for r in rows], "waiting": int(waiting)}


def _audio(path, name: str) -> FileResponse:
    kind = {"wav": "audio/wav", "webm": "audio/webm", "ogg": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
            "mp4": "audio/mp4"}.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, no-store",
                                                        "Content-Disposition": f"inline; filename={name}{path.suffix}"})


@router.get("/admin/consent-reviews/{attempt_id}/recording")
def consent_recording(attempt_id: str, who: str = Depends(_admin)) -> FileResponse:
    row = _attempt(attempt_id)
    path = _api().artifacts.find(f"liveness-{row['owner']}", row["audio_sha"]) if row["audio_sha"] else None
    if path is None:
        raise HTTPException(status_code=404, detail="That recording is not kept.")
    return _audio(path, f"consent-{attempt_id}")


@router.get("/admin/consent-reviews/{attempt_id}/source")
def consent_source(attempt_id: str, who: str = Depends(_admin)) -> FileResponse:
    api = _api()
    row = _attempt(attempt_id)
    record = api.repo.get(row["video_id"])
    path = api.consent_reference(row["video_id"], record, row["speaker"]) if record is not None else None
    if path is None:
        raise HTTPException(status_code=404, detail="There is too little of the speaker in that video to play.")
    return _audio(path, f"speaker-{attempt_id}")


class ConsentDecision(BaseModel):
    decision: str
    reason: str = Field(default="", max_length=500)


@router.post("/admin/consent-reviews/{attempt_id}")
def decide_consent(attempt_id: str, req: ConsentDecision, who: str = Depends(_admin)) -> dict:
    api = _api()
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="Approve or reject.")
    reason = _need_reason(req.reason)
    row = _attempt(attempt_id)
    if row["status"] != "review":
        raise HTTPException(status_code=409, detail="That check is not waiting for review any more.")
    approve = req.decision == "approve"
    from app.safety import consent as consent_mod
    with api.database.tx() as c:
        c.execute("UPDATE liveness_attempts SET status = ?, reason = ?, tip = ?, reviewed_by = ?, review_reason = ?, reviewed_at = ? "
                  "WHERE id = ? AND status = 'review'",
                  ("passed" if approve else "failed", APPROVED if approve else REJECTED, "" if approve else consent_mod.TIP_VOICE,
                   who, reason, now_iso(), attempt_id))
        admin.audit_in(c, who, "consent_approve" if approve else "consent_reject", row["owner"], reason,
                       {"attempt_id": attempt_id, "video_id": row["video_id"], "similarity": row["similarity"], "wer": row["wer"],
                        "rule": row["rule"]})
        api.inbox.add_in(c, row["owner"], "consent_decided",
                         "Your consent recording was approved." if approve else "Your consent recording was not approved.",
                         body=APPROVED if approve else REJECTED, link=f"#v/{row['video_id']}", video_id=row["video_id"])
        analytics.track_in(c, "consent.reviewed", who, {"approved": approve})
        row = c.execute("SELECT * FROM liveness_attempts WHERE id = ?", (attempt_id,)).fetchone()
    return _review_row(row)
