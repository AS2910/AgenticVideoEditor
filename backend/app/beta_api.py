"""Beta kit (routes).

Admins only (AVE_ADMIN_OWNERS; everyone else gets 404):
    POST /admin/beta/join     {who, email?}: `who` is an owner id or an address; into the
                              cohort (app.beta.join: its flags on, $10 of credits once),
                              audited; with email (the default) the beta invite goes to
                              their address, worded for someone with an account
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import admin, beta

router = APIRouter(tags=["beta"])


def _api():
    from app.api import main
    return main


def _admin_writer(request: Request) -> str:
    from app.admin_api import _admin
    return _admin(request)


def _who(text: str) -> str:
    """An owner id Voltage knows, or the one person with exactly this address."""
    from app.admin_api import _known
    text = text.strip()
    if "@" in text and not text.startswith(("acct:", "google:", "email:")):
        owners = [r["owner"] for r in admin.find(_api().database, text) if text.lower() in r["emails"]]
        if len(owners) != 1:
            raise HTTPException(status_code=404, detail="Nobody has signed in with that address." if not owners
                                else "More than one person has that address. Use their owner id.")
        return owners[0]
    return _known(text)


class Join(BaseModel):
    who: str = Field(min_length=2, max_length=320)
    email: bool = True


@router.post("/admin/beta/join")
def join_beta(req: Join, who: str = Depends(_admin_writer)) -> dict:
    api = _api()
    owner = _who(req.who)
    made = beta.join(api.database, api.flags, owner)
    admin.audit(api.database, who, "beta_join", owner, "", {"credits": made["credits"], "again": not made["joined"]})
    sent = False
    if req.email and made["joined"]:
        to = admin.proven_address(api.database, owner)
        sent = bool(to) and beta.invite_email(api, to, existing=True)
    return {"owner": owner, **made, "emailed": sent}

