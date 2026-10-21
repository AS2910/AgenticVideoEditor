"""Launch item 5: sign-up and sign-in with an email and a password.

    GET  /auth/options                      what this Voltage offers (Google, password, emailed link, invite only)
    POST /auth/signup                       {email, password, accept_terms, invite_code?} -> a verify email
    POST /auth/verify/resend                {email} -> a fresh verify email (same answer either way)
    GET  /auth/verify?token=                the emailed link: verified, signed in, Home
    POST /auth/password/login               {email, password} -> the session
    POST /auth/password/forgot              {email} -> a reset email (same answer either way)
    POST /auth/password/reset               {token, password} -> new password, signed in, other sessions out
    POST /auth/change-email                 {new_email, password} -> a confirm link to the new address
    GET  /auth/change-email/confirm?token=  the emailed link: the address changes

An account's owner id is `acct:<id>` and never changes with its address.
Answers about an address never say whether it has an account. With the
`launch.invite_only` flag on for everyone, a new account needs a waiting
workspace invite for its address or one of the codes in AVE_INVITE_CODES.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.store import accounts as store

router = APIRouter(tags=["accounts"])

# The version of the Terms a sign-up accepts (the pages are drafts until legal replaces them).
TERMS_VERSION = os.environ.get("AVE_TERMS_VERSION") or "draft-2026-10-22"
SENT = "If that address can use Voltage, an email is on its way. It can take a minute."


def _api():
    from app.api import main
    return main


def _on() -> None:
    if _api().settings.auth_mode == "off":
        raise HTTPException(status_code=404, detail="Sign-in is off.")


def _csrf(request: Request) -> None:
    api = _api()
    if request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")


def _link(path: str) -> str:
    return f"{_api().settings.public_url}/api{path}"


def _send(to: str, kind: str, subject: str, lines: list[str], owner: str | None = None) -> None:
    api = _api()
    try:
        api.email_sender.send(api.email_mod.Email(to=to, kind=kind, subject=subject, body="\n".join(lines), owner=owner))
    except Exception:  # noqa: BLE001 - the answer is the same; the log says what failed
        api.log.exception("%s email", kind)


def _session(response: Response, account: store.Account) -> None:
    api = _api()
    response.set_cookie(
        api.auth.SESSION_COOKIE,
        api.auth.sign({"sub": account.id, "email": account.email, "name": None, "picture": None,
                       "provider": "acct", "sv": account.session_version}, api.settings.session_secret or ""),
        max_age=api.auth.SESSION_SECONDS, httponly=True, samesite="lax", secure=api._secure(), path="/")


def _welcome(account: store.Account) -> None:
    """The first steps of a new person: the funnel, their address for email, the sample."""
    api = _api()
    api.email_mod.remember_address(api.database, account.owner, account.email)
    api._signed_in(account.owner)
    try:
        from app.tutorial import sample
        sample.ensure(account.owner)
    except Exception:  # noqa: BLE001 - the sample is a nicety; sign-in never fails over it
        api.log.exception("could not make the sample project for a new owner")


def invite_only() -> bool:
    return _api().flags.enabled("launch.invite_only")


def may_join(email: str, code: str | None) -> bool:
    """With invite-only on: a waiting workspace invite for the address, or a valid code."""
    if not invite_only():
        return True
    codes = {c.strip() for c in (os.environ.get("AVE_INVITE_CODES") or "").split(",") if c.strip()}
    if code and code.strip() in codes:
        return True
    api = _api()
    with api.database.tx() as c:
        return c.execute("SELECT 1 FROM workspace_invites WHERE lower(email) = ? AND accepted_at IS NULL AND revoked_at IS NULL "
                         "AND expires_at > ?", (email.lower(), api.now_iso())).fetchone() is not None


INVITE_ONLY = "Voltage is invite-only for now. Ask for an invite, or enter the invite code you were given."


@router.get("/auth/options")
def options() -> dict:
    api = _api()
    mode = api.settings.auth_mode
    return {"mode": mode, "google": mode == "google", "password": mode != "off",
            "email_link": mode != "off" and api.flags.enabled("golive.g2", api.LOCAL_OWNER),
            "invite_only": mode != "off" and invite_only(), "terms_version": TERMS_VERSION}


class SignUp(BaseModel):
    email: str
    password: str
    accept_terms: bool = False
    invite_code: str | None = None


@router.post("/auth/signup", status_code=201)
def sign_up(req: SignUp, request: Request) -> dict:
    _on()
    _csrf(request)
    if not req.accept_terms:
        raise HTTPException(status_code=422, detail="Accept the Terms and the Privacy notice to make an account.")
    try:
        address = store.clean_email(req.email)
        store.check_password(req.password)
    except store.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not may_join(address, req.invite_code):
        raise HTTPException(status_code=403, detail=INVITE_ONLY)
    api = _api()
    allow = api.settings.allowed_emails
    if allow and not api.auth.allowed(api.auth.Identity("x", address), allow):
        raise HTTPException(status_code=403, detail="This Voltage is private; that address is not on its list.")
    try:
        account, token = store.sign_up(api.database, address, req.password, TERMS_VERSION)
    except store.AccountError:
        # Taken: say the same as for a new address, and tell the owner of the address instead.
        _send(address, "account_exists", "Someone tried to sign up with your address",
              ["Hi,", "", "Someone (perhaps you) tried to make a Voltage account with this address, which already has one.",
               "", f"To sign in, or reset your password, go to {api.settings.public_url}/#login", "",
               "If it was not you, you can ignore this email."])
        return {"sent": True, "message": SENT}
    _send(address, "verify_email", "Confirm your email for Voltage",
          ["Hi,", "", "Open this link to confirm your address and sign in. It works once, for 48 hours.", "",
           _link(f"/auth/verify?token={token}"), "", "If you did not sign up, you can ignore this email."], account.owner)
    api.analytics.track("account.created", account.owner, {"terms_version": TERMS_VERSION})
    return {"sent": True, "message": SENT}


class EmailOnly(BaseModel):
    email: str


@router.post("/auth/verify/resend")
def resend_verify(req: EmailOnly, request: Request) -> dict:
    _on()
    _csrf(request)
    api = _api()
    try:
        account = store.by_email(api.database, store.clean_email(req.email))
    except store.AccountError:
        account = None
    if account is not None and not account.verified:
        token = store.new_token(api.database, account, "verify", account.email)
        _send(account.email, "verify_email", "Confirm your email for Voltage",
              ["Hi,", "", "Open this link to confirm your address and sign in. It works once, for 48 hours.", "",
               _link(f"/auth/verify?token={token}")], account.owner)
    return {"sent": True, "message": SENT}


def _landing(where: str) -> RedirectResponse:
    return RedirectResponse(f"{_api().settings.public_url}/#{where}", status_code=302)


@router.get("/auth/verify")
def verify(token: str | None = None) -> Response:
    _on()
    api = _api()
    try:
        account, _ = store.use_token(api.database, "verify", token)
    except store.AccountError as exc:
        return _landing(f"login?error={api.quote(str(exc))}")
    api.analytics.track("account.verified", account.owner, {})
    _welcome(account)
    response = _landing("home")
    _session(response, account)
    return response


class PasswordLogin(BaseModel):
    email: str
    password: str


@router.post("/auth/password/login")
def password_login(req: PasswordLogin, request: Request, response: Response) -> dict:
    _on()
    _csrf(request)
    api = _api()
    try:
        account = store.authenticate(api.database, req.email, req.password)
    except store.AccountError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    if not account.verified:
        raise HTTPException(status_code=403, detail={"code": "unverified", "message":
                            "Confirm your email first: open the link we sent. Not there? Send it again."})
    _welcome(account)
    _session(response, account)
    return {"signed_in": True, "email": account.email}


@router.post("/auth/password/forgot")
def forgot(req: EmailOnly, request: Request) -> dict:
    _on()
    _csrf(request)
    api = _api()
    try:
        account = store.by_email(api.database, store.clean_email(req.email))
    except store.AccountError:
        account = None
    if account is not None:
        token = store.new_token(api.database, account, "reset", account.email)
        _send(account.email, "password_reset", "Reset your Voltage password",
              ["Hi,", "", "Open this link to choose a new password. It works once, for one hour.", "",
               f"{api.settings.public_url}/#reset/{token}", "",
               "If you did not ask for it, you can ignore this email; your password stays as it is."], account.owner)
    return {"sent": True, "message": SENT}


class Reset(BaseModel):
    token: str
    password: str


@router.post("/auth/password/reset")
def reset(req: Reset, request: Request, response: Response) -> dict:
    _on()
    _csrf(request)
    api = _api()
    try:
        store.check_password(req.password)
        account, _ = store.use_token(api.database, "reset", req.token)
        account = store.set_password(api.database, account.id, req.password)
    except store.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not account.verified:          # the reset link reached the address, which proves it
        with api.database.tx() as c:
            c.execute("UPDATE accounts SET verified_at = ? WHERE id = ?", (api.now_iso(), account.id))
        account = store.by_id(api.database, account.id)
    api.analytics.track("account.password_reset", account.owner, {})
    _session(response, account)
    return {"signed_in": True, "email": account.email}


class ChangeEmail(BaseModel):
    new_email: str
    password: str


def _account_of(request: Request) -> store.Account:
    api = _api()
    who = api.signed_in_identity(request)
    if who is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if who.provider != "acct":
        raise HTTPException(status_code=409, detail="Your address comes from your Google account; change it there.")
    account = store.by_id(api.database, who.sub)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return account


@router.post("/auth/change-email")
def change_email(req: ChangeEmail, request: Request) -> dict:
    _on()
    _csrf(request)
    api = _api()
    account = _account_of(request)
    try:
        store.authenticate(api.database, account.email, req.password)
        address = store.clean_email(req.new_email)
    except store.AccountError as exc:
        raise HTTPException(status_code=422, detail="That password is not right." if "match" in str(exc) else str(exc)) from None
    if address == account.email:
        raise HTTPException(status_code=422, detail="That is the address you have now.")
    if store.by_email(api.database, address) is not None:
        raise HTTPException(status_code=422, detail="Another account uses that address.")
    token = store.new_token(api.database, account, "change_email", address)
    _send(address, "change_email", "Confirm your new email for Voltage",
          ["Hi,", "", "Open this link to make this your Voltage address. It works once, for 24 hours.", "",
           _link(f"/auth/change-email/confirm?token={token}")], account.owner)
    _send(account.email, "change_email_notice", "Your Voltage address is changing",
          ["Hi,", "", f"Someone signed in to your account asked to change its address to {address}.",
           "If it was not you, reset your password now and the change will not go through."], account.owner)
    return {"sent": True, "message": f"We sent a link to {address}. Open it to finish the change."}


@router.get("/auth/change-email/confirm")
def confirm_email_change(token: str | None = None) -> Response:
    _on()
    api = _api()
    try:
        account, address = store.use_token(api.database, "change_email", token)
        account = store.change_email(api.database, account.id, address)
    except store.AccountError as exc:
        return _landing(f"login?error={api.quote(str(exc))}")
    api.email_mod.remember_address(api.database, account.owner, account.email)
    api.analytics.track("account.email_changed", account.owner, {})
    response = _landing("settings")
    _session(response, account)
    return response
