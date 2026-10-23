"""Launch item 9: the email preview for admins (it never sends anything).

    GET /admin/emails/preview          {kinds: [{kind, label}]}
    GET /admin/emails/preview/{kind}   {kind, label, subject, html, text} with sample data

Anyone who is not an admin gets a 404, as with the other admin routes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.notify import templates

router = APIRouter(tags=["admin"])


def _admin(request: Request) -> None:
    from app.api import main
    main._admin_or_404(request)


def _settings():
    from app.api import main
    return main.settings


@router.get("/admin/emails/preview")
def list_previews(request: Request) -> dict:
    _admin(request)
    return {"kinds": [{"kind": k, "label": templates.LABELS[k]} for k in templates.KINDS]}


@router.get("/admin/emails/preview/{kind}")
def one_preview(kind: str, request: Request) -> dict:
    _admin(request)
    if kind not in templates.KINDS:
        raise HTTPException(status_code=404, detail="There is no email of that kind.")
    data = dict(templates.SAMPLES[kind])
    if kind == "account_deleted":
        data["removed"], data["kept"] = templates.deletion_lists(_settings().consent_retention_years)
    if kind == "invoice":
        s = _settings()
        from app.billing import gst
        data["seller"] = {"name": s.seller_name, "gstin": s.seller_gstin, "state": s.seller_state,
                          "state_name": gst.STATES.get(s.seller_state, s.seller_state)}
    r = templates.render(kind, public_url=_settings().public_url, **data)
    return {"kind": kind, "label": templates.LABELS[kind], "subject": r.subject, "html": r.html, "text": r.text}
