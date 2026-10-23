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
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import admin, analytics, billing
from app.timefmt import iso

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
