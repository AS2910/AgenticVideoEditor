"""Accounts with an email and a password (launch item 5).

A person who signs up gets a stable owner id, `acct:<id>`, that never
changes when their address does. Passwords are kept as scrypt hashes. Every
emailed link is a one-use token, of which only a hash is stored:

    sign_up(db, email, password, terms_version) -> (Account, verify token)
    authenticate(db, email, password) -> Account          raises AccountError
    use_token(db, kind, token) -> (Account, email)        one use, expiring
    new_token(db, account, kind, email) -> token
    set_password(db, account_id, password)                signs other sessions out
    change_email(db, account_id, new_email)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.store.db import Database
from app.timefmt import iso, now_iso

MIN_PASSWORD = 10
TOKEN_HOURS = {"verify": 48, "reset": 1, "change_email": 24}
# scrypt: 16 MiB of memory per hash (n=2**14, r=8), a few tens of ms.
_N, _R, _P = 2 ** 14, 8, 1


class AccountError(ValueError):
    """A sign-up or sign-in that cannot go on, with the sentence to show."""


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    verified: bool
    session_version: int

    @property
    def owner(self) -> str:
        return f"acct:{self.id}"


def clean_email(email: str | None) -> str:
    address = " ".join((email or "").split()).lower()
    local, _, domain = address.partition("@")
    if not local or "." not in domain or " " in address or len(address) > 254:
        raise AccountError("That does not look like an email address.")
    return address


def check_password(password: str | None) -> str:
    password = password or ""
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters for your password.")
    if len(password) > 256:
        raise AccountError("That password is too long (256 characters at most).")
    return password


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def _matches(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


# A real hash to check against when the address has no account, so a wrong
# address takes as long as a wrong password (no account enumeration by timing).
_DUMMY = hash_password("not-a-real-password", b"0" * 16)


def _row(r) -> Account:
    return Account(r["id"], r["email"], bool(r["verified_at"]), int(r["session_version"]))


def by_id(db: Database, account_id: str) -> Account | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM accounts WHERE id = ? AND deleted_at IS NULL", (account_id,)).fetchone()
    return _row(r) if r else None


def by_email(db: Database, email: str) -> Account | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM accounts WHERE email = ? AND deleted_at IS NULL", (email.lower(),)).fetchone()
    return _row(r) if r else None


def sign_up(db: Database, email: str, password: str, terms_version: str | None = None) -> tuple[Account, str]:
    address = clean_email(email)
    check_password(password)
    with db.tx() as c:
        if c.execute("SELECT 1 FROM accounts WHERE email = ?", (address,)).fetchone():
            raise AccountError("There is already an account with that address. Sign in, or reset your password.")
        account_id = secrets.token_hex(8)
        now = now_iso()
        c.execute("INSERT INTO accounts (id, email, password_hash, created_at, terms_version, terms_at) VALUES (?, ?, ?, ?, ?, ?)",
                  (account_id, address, hash_password(password), now, terms_version, now if terms_version else None))
    account = by_id(db, account_id)
    return account, new_token(db, account, "verify", address)  # type: ignore[arg-type]


def authenticate(db: Database, email: str, password: str) -> Account:
    """The account, or AccountError with one sentence for every wrong case."""
    try:
        address = clean_email(email)
    except AccountError:
        address = ""
    with db.tx() as c:
        r = c.execute("SELECT * FROM accounts WHERE email = ? AND deleted_at IS NULL", (address,)).fetchone()
    if r is None:
        _matches(password or "", _DUMMY)
        raise AccountError("That email and password do not match an account.")
    if not _matches(password or "", r["password_hash"]):
        raise AccountError("That email and password do not match an account.")
    return _row(r)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(db: Database, account: Account, kind: str, email: str) -> str:
    """A fresh one-use link token; any older unused one of the same kind stops working."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with db.tx() as c:
        c.execute("UPDATE auth_tokens SET used_at = ? WHERE account_id = ? AND kind = ? AND used_at IS NULL",
                  (now_iso(), account.id, kind))
        c.execute("INSERT INTO auth_tokens (token_hash, kind, account_id, email, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                  (_hash(token), kind, account.id, email, now_iso(), iso(now + timedelta(hours=TOKEN_HOURS[kind]))))
    return token


def use_token(db: Database, kind: str, token: str | None) -> tuple[Account, str]:
    """Spend a link token: (account, the address it went to)."""
    with db.tx() as c:
        r = c.execute("SELECT * FROM auth_tokens WHERE token_hash = ? AND kind = ?", (_hash(token or ""), kind)).fetchone()
        if r is None:
            raise AccountError("That link is not valid. Ask for a new one.")
        if r["used_at"]:
            raise AccountError("That link has been used already. Ask for a new one.")
        if r["expires_at"] <= now_iso():
            raise AccountError("That link has expired. Ask for a new one.")
        c.execute("UPDATE auth_tokens SET used_at = ? WHERE token_hash = ?", (now_iso(), r["token_hash"]))
        if kind == "verify":
            c.execute("UPDATE accounts SET verified_at = COALESCE(verified_at, ?) WHERE id = ? AND email = ?",
                      (now_iso(), r["account_id"], r["email"]))
    account = by_id(db, r["account_id"])
    if account is None:
        raise AccountError("That account no longer exists.")
    return account, r["email"]


def set_password(db: Database, account_id: str, password: str) -> Account:
    """A new password; every other session of this account is signed out."""
    check_password(password)
    with db.tx() as c:
        c.execute("UPDATE accounts SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                  (hash_password(password), account_id))
        c.execute("UPDATE auth_tokens SET used_at = ? WHERE account_id = ? AND kind = 'reset' AND used_at IS NULL",
                  (now_iso(), account_id))
    return by_id(db, account_id)  # type: ignore[return-value]


def change_email(db: Database, account_id: str, new_email: str) -> Account:
    address = clean_email(new_email)
    with db.tx() as c:
        taken = c.execute("SELECT id FROM accounts WHERE email = ? AND id != ?", (address, account_id)).fetchone()
        if taken:
            raise AccountError("Another account uses that address.")
        c.execute("UPDATE accounts SET email = ?, verified_at = ?, session_version = session_version + 1 WHERE id = ?",
                  (address, now_iso(), account_id))
    return by_id(db, account_id)  # type: ignore[return-value]


def delete(db: Database, account_id: str) -> None:
    """The sign-in goes; the address is free to sign up again."""
    with db.tx() as c:
        c.execute("DELETE FROM auth_tokens WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
