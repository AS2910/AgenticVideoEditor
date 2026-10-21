"""G2: roles and invites, and email sign-in (routes).

Who is acting is worked out once per request (`app.api.main._resolve_acting`):
the signed-in person, the workspace they chose (cookie `ave_workspace`), and
their role in it. Acting in someone else's workspace, every existing route
sees the workspace owner as `owner`, so the work is theirs; the role decides
what may be done (`role_refusal`, enforced by a middleware before any route
runs), and the person is recorded on each charge (`usage.by`) so their
monthly spend limit holds.

Owner: everything. Editor: everything except members and billing. Reviewer:
reads, and comments on videos. With sign-in off there is one account, the
local owner, and it is the Owner.

Email sign-in: `POST /auth/email` emails a one-use link (15 minutes) through
the notify interface (the fake outbox until a provider is set up);
`GET /auth/email/callback` turns it into the same session cookie Google's
sign-in sets. An address a Google sign-in already remembered reaches that
same account.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.store import members as members_store

router = APIRouter(tags=["workspace"])

WORKSPACE_COOKIE = "ave_workspace"
_ID = r"[^/]+"
# Reviewer: reads, and comments (a new comment on a video, a reply on one).
REVIEWER_WRITES = (
    re.compile(rf"^/videos/{_ID}/comments$"),
    re.compile(rf"^/videos/{_ID}/comments/{_ID}/replies$"),
)
# Anyone may do these whatever their role: their own sign-in, invites, which workspace, their own notifications.
OPEN_TO_ALL = (re.compile(r"^/auth/"), re.compile(r"^/invites/"), re.compile(r"^/workspace/switch$"),
               re.compile(r"^/me/notifications"))
OWNER_ONLY = (re.compile(r"^/workspace/members"), re.compile(r"^/workspace/invites"), re.compile(r"^/billing"))
READS = ("GET", "HEAD", "OPTIONS")


def role_refusal(role: str, method: str, path: str) -> str | None:
    """The sentence refusing this request for this role, or None when it may go."""
    path = path[4:] if path.startswith("/api/") else path
    if role == "owner" or any(p.match(path) for p in OPEN_TO_ALL):
        return None
    if any(p.match(path) for p in OWNER_ONLY):
        return "Only the workspace owner can manage members and billing."
    if role == "editor":
        return None
    if role == "reviewer":
        if method in READS or (method == "POST" and any(p.match(path) for p in REVIEWER_WRITES)):
            return None
        return "As a Reviewer you can watch and comment. Ask the owner to make you an Editor to change things."
    return "You are not in this workspace."


def _api():
    from app.api import main
    return main


def _owner(request: Request) -> str:
    return _api().current_owner(request)


def _acting():
    return _api().acting.get()


def _flag(owner: str) -> None:
    if not _api().flags.enabled("golive.g2", owner):
        raise HTTPException(status_code=404, detail="Not found")


def _key() -> str:
    return _api().share_key


def _url(path: str) -> str:
    return f"{_api().settings.public_url}/{path}"


def _who(user: str) -> dict:
    """A person as the Members page names them."""
    api = _api()
    email = api.email_mod.address_for(api.database, user)
    return {"member": user, "email": email, "name": None}


# ── reading ──

@router.get("/workspace")
def get_workspace(owner: str = Depends(_owner)) -> dict:
    """The workspace being worked in, your role in it, and the workspaces you can switch to."""
    api = _api()
    _flag(owner)
    me = _acting()
    user = me.user if me else owner
    wid = members_store.workspace_of(api.database, owner)
    ws = members_store.workspace(api.database, wid)
    return {"workspace": {"workspace_id": wid, "name": ws["name"] if ws else "My workspace", "own": user == owner},
            "you": {"user": user, "role": me.role if me else "owner"},
            "workspaces": members_store.workspaces_for(api.database, user)}


def _members_page(owner: str) -> dict:
    api = _api()
    wid = members_store.workspace_of(api.database, owner)
    since = api.iso(api.month_start())
    rows = []
    for m in members_store.members(api.database, wid):
        rows.append({**m.to_dict(), "role_word": members_store.ROLE_WORDS[m.role],
                     "shares": members_store.shares(api.database, wid, m.member),
                     "spent_usd": round(api.ledger.spent_usd_by_actor(m.member, wid, since), 4)})
    owner_row = {**_who(owner), "role": "owner", "role_word": "Owner",
                 "spent_usd": round(api.ledger.spent_usd_by_owner(owner, since), 4)}
    return {"workspace_id": wid, "owner": owner_row, "members": rows,
            "invites": [_invite_view(i) for i in members_store.invites(api.database, wid)],
            "roles": [{"role": r, "word": members_store.ROLE_WORDS[r]} for r in members_store.MEMBER_ROLES],
            "sign_in": api.settings.auth_mode != "off"}


def _invite_view(row: dict) -> dict:
    return {k: row[k] for k in ("id", "email", "role", "spend_limit_usd", "created_at", "expires_at", "state")} | {
        "link": _url(f"#invite/{members_store.invite_token(_key(), row)}")}


@router.get("/workspace/members")
def list_members(owner: str = Depends(_owner)) -> dict:
    """Owner only: who is in the workspace, their role, limit and spend this month, and waiting invites."""
    _flag(owner)
    return _members_page(owner)


# ── changing ──

class InviteRequest(BaseModel):
    email: str
    role: str = "editor"
    spend_limit_usd: float | None = None
    # Launch item 1: what a Reviewer will see (project and video ids of this workspace).
    project_ids: list[str] = []
    video_ids: list[str] = []


def _own_shares(owner: str, project_ids: list[str], video_ids: list[str]) -> dict:
    """The ids, each checked to be the owner's own (404 otherwise)."""
    api = _api()
    for pid in project_ids:
        api._owned_project(pid, owner)
    for vid in video_ids:
        api._owned(vid, owner)
    return {"projects": project_ids, "videos": video_ids}


@router.post("/workspace/invites", status_code=201)
def send_invite(req: InviteRequest, owner: str = Depends(_owner)) -> dict:
    """Invite someone by email as an Editor or a Reviewer. The email goes
    through the notify interface; the page also shows the link to copy."""
    api = _api()
    _flag(owner)
    wid = members_store.workspace_of(api.database, owner)
    try:
        shares = _own_shares(owner, req.project_ids, req.video_ids)
        row, token = members_store.invite(api.database, _key(), wid, req.email, req.role, owner, req.spend_limit_usd, shares)
    except members_store.MemberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    word = members_store.ROLE_WORDS[row["role"]]
    can = "watch and comment on videos" if row["role"] == "reviewer" else "edit videos and projects"
    try:
        api.email_sender.send(api.email_mod.Email(
            to=row["email"], kind="workspace_invite", owner=owner, workspace_id=wid,
            subject="You are invited to a Voltage workspace",
            body="\n".join(["Hi,", "", f"You have been invited to a Voltage workspace as {'a' if word != 'Editor' else 'an'} {word}, "
                            f"so you can {can}.", "", f"Accept the invite: {_url(f'#invite/{token}')}", "",
                            f"The link works until {row['expires_at'][:10]}."])))
    except Exception:  # noqa: BLE001 - the invite is made; the page shows the link to copy
        api.log.exception("workspace invite email")
    with api.database.tx() as c:
        api.activity_log.record(c, "member.invited", api.user_actor(owner), target=row["id"], payload={"role": row["role"]},
                                workspace_id=wid)
    return {**_members_page(owner), "invite": _invite_view(row)}


@router.delete("/workspace/invites/{invite_id}")
def revoke_invite(invite_id: str, owner: str = Depends(_owner)) -> dict:
    api = _api()
    _flag(owner)
    wid = members_store.workspace_of(api.database, owner)
    if not members_store.revoke_invite(api.database, wid, invite_id):
        raise HTTPException(status_code=404, detail="That invite is not waiting any more.")
    return _members_page(owner)


class SharesChange(BaseModel):
    project_ids: list[str] = []
    video_ids: list[str] = []


@router.put("/workspace/members/{member}/shares")
def change_shares(member: str, req: SharesChange, owner: str = Depends(_owner)) -> dict:
    """Owner only: replace the projects and videos shared with a member (a
    Reviewer reads only these)."""
    api = _api()
    _flag(owner)
    wid = members_store.workspace_of(api.database, owner)
    shares = _own_shares(owner, req.project_ids, req.video_ids)
    try:
        members_store.set_shares(api.database, wid, member, shares, owner)
    except members_store.MemberError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _members_page(owner)


class MemberChange(BaseModel):
    role: str | None = None
    spend_limit_usd: float | None = None


@router.patch("/workspace/members/{member}")
def change_member(member: str, req: MemberChange, owner: str = Depends(_owner)) -> dict:
    """Change a member's role, or their monthly spend limit (null clears it)."""
    api = _api()
    _flag(owner)
    wid = members_store.workspace_of(api.database, owner)
    try:
        members_store.set_role(api.database, wid, member, req.role, req.spend_limit_usd,
                               clear_limit="spend_limit_usd" in req.model_fields_set and req.spend_limit_usd is None)
    except members_store.MemberError as exc:
        raise HTTPException(status_code=422 if "not in" not in str(exc) else 404, detail=str(exc)) from None
    with api.database.tx() as c:
        api.activity_log.record(c, "member.changed", api.user_actor(owner), target=member,
                                payload={k: v for k, v in req.model_dump().items() if k in req.model_fields_set}, workspace_id=wid)
    return _members_page(owner)


@router.delete("/workspace/members/{member}")
def remove_member(member: str, owner: str = Depends(_owner)) -> dict:
    """Take someone out of the workspace. What they made stays."""
    api = _api()
    _flag(owner)
    wid = members_store.workspace_of(api.database, owner)
    if not members_store.remove(api.database, wid, member):
        raise HTTPException(status_code=404, detail="That person is not in this workspace.")
    with api.database.tx() as c:
        api.activity_log.record(c, "member.removed", api.user_actor(owner), target=member, workspace_id=wid)
    return _members_page(owner)


class Switch(BaseModel):
    workspace_id: str | None = None


@router.post("/workspace/switch")
def switch_workspace(req: Switch, request: Request, response: Response) -> dict:
    """Work in another workspace you belong to (null: your own)."""
    api = _api()
    me = api.signed_in_user(request)
    if req.workspace_id is None:
        response.delete_cookie(WORKSPACE_COOKIE, path="/")
        return {"workspace_id": None}
    role = members_store.role_in(api.database, req.workspace_id, me)
    if role is None:
        raise HTTPException(status_code=404, detail="You are not in that workspace.")
    response.set_cookie(WORKSPACE_COOKIE, req.workspace_id, max_age=api.auth.SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=api._secure(), path="/")
    return {"workspace_id": req.workspace_id, "role": role}


# ── the invite link ──

def _refused(exc: members_store.LinkRefused):
    return HTTPException(status_code=410 if exc.gone else 404, detail=str(exc))


@router.get("/invites/{token}")
def open_invite(token: str) -> dict:
    """Public: what the invite is for (no account needed to read it)."""
    api = _api()
    try:
        row = members_store.resolve_invite(api.database, _key(), token)
    except members_store.LinkRefused as exc:
        raise _refused(exc) from None
    ws = members_store.workspace(api.database, row["workspace_id"])
    inviter = api.email_mod.address_for(api.database, row["invited_by"])
    return {"email": row["email"], "role": row["role"], "role_word": members_store.ROLE_WORDS[row["role"]],
            "workspace_name": ws["name"] if ws else "A workspace", "invited_by": inviter, "expires_at": row["expires_at"],
            "sign_in": api.settings.auth_mode != "off"}


@router.post("/invites/{token}/accept")
def accept_invite(token: str, request: Request, response: Response) -> dict:
    """Join the workspace as the signed-in person, and start working in it."""
    api = _api()
    if api.settings.auth_mode == "off":
        raise HTTPException(status_code=409, detail="Sign-in is off on this Voltage, so it has one account and it is the Owner. "
                                                    "Invites work once sign-in is on.")
    me = api.signed_in_user(request)
    who = api.signed_in_identity(request)
    try:
        joined = members_store.accept(api.database, _key(), token, me, who.email if who else None, who.name if who else None)
    except members_store.LinkRefused as exc:
        raise _refused(exc) from None
    except members_store.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if who is not None:
        api.email_mod.remember_address(api.database, me, who.email)
    ws = members_store.workspace(api.database, joined.workspace_id)
    with api.database.tx() as c:
        api.activity_log.record(c, "member.joined", api.user_actor(me), target=me, payload={"role": joined.role},
                                workspace_id=joined.workspace_id)
    response.set_cookie(WORKSPACE_COOKIE, joined.workspace_id, max_age=api.auth.SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=api._secure(), path="/")
    return {"workspace_id": joined.workspace_id, "workspace_name": ws["name"] if ws else "", "role": joined.role,
            "role_word": members_store.ROLE_WORDS[joined.role]}


# ── email sign-in ──

class EmailSignIn(BaseModel):
    email: str


def _email_sign_in_on() -> bool:
    api = _api()
    return api.settings.auth_mode != "off" and api.flags.enabled("golive.g2", api.LOCAL_OWNER)


@router.get("/auth/email")
def email_sign_in_available() -> dict:
    return {"available": _email_sign_in_on()}


@router.post("/auth/email")
def send_sign_in_link(req: EmailSignIn) -> dict:
    """Email a one-use sign-in link. The answer is the same whether or not
    the address has an account, so it tells nobody who uses Voltage."""
    api = _api()
    if not _email_sign_in_on():
        raise HTTPException(status_code=404, detail="Email sign-in is off.")
    try:
        address = members_store.clean_email(req.email)
    except members_store.MemberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    allow = api.settings.allowed_emails
    if not allow or address in {a.lower() for a in allow}:
        token = members_store.login_link(api.database, _key(), address)
        try:
            api.email_sender.send(api.email_mod.Email(
                to=address, kind="sign_in", subject="Your Voltage sign-in link",
                body="\n".join(["Hi,", "", "Open this link to sign in to Voltage. It works once, for 15 minutes.", "",
                                f"{api.settings.public_url}/api/auth/email/callback?token={token}", "",
                                "If you did not ask for it, you can ignore this email."])))
        except Exception:  # noqa: BLE001
            api.log.exception("sign-in email")
    return {"sent": True, "email": address}


@router.get("/auth/email/callback")
def email_sign_in(token: str | None = None) -> Response:
    """From the emailed link: the session cookie, then Home."""
    api = _api()
    if not _email_sign_in_on():
        raise HTTPException(status_code=404, detail="Email sign-in is off.")
    try:
        address = members_store.use_login_link(api.database, _key(), token)
    except members_store.LinkRefused as exc:
        raise _refused(exc) from None
    known = members_store.owner_for_email(api.database, address)
    provider, sub = known.split(":", 1) if known and ":" in known else ("email", address)
    who = api.auth.Identity(sub, address, None, None, provider)
    if api._new_person_refused(who.owner, address):           # launch item 5: invite-only
        from app.accounts_api import INVITE_ONLY
        raise HTTPException(status_code=403, detail=INVITE_ONLY)
    api.email_mod.remember_address(api.database, who.owner, address)
    api._signed_in(who.owner)                                    # G7: the funnel's first steps
    try:
        from app.tutorial import sample
        sample.ensure(who.owner)
    except Exception:  # noqa: BLE001
        api.log.exception("could not make the sample project for a new owner")
    response = RedirectResponse(api.settings.public_url + "/", status_code=302)
    response.set_cookie(api.auth.SESSION_COOKIE,
                        api.auth.sign({"sub": who.sub, "email": address, "name": None, "picture": None, "provider": provider},
                                      api.settings.session_secret or ""),
                        max_age=api.auth.SESSION_SECONDS, httponly=True, samesite="lax", secure=api._secure(), path="/")
    return response
