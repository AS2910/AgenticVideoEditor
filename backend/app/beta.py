"""Beta kit (the beta starts 28 October 2026).

    BETA_CREDITS                            what a person in the cohort is given, once
    pending_invite(db, email) / mark_invited(db, email)    a waitlist address invited to the beta
    invited_addresses(db) -> set            every address invited to the beta
    invite_email(api, to, name, existing)   the beta invite (templates `beta_invite`); never raises

A waitlist row's "Invite to beta" (landing_api) marks the row invited, as
Send invite does, and remembers the address in `meta` under
`beta_invite:{email}`, so the person joins the cohort when they first sign in.
"""
from __future__ import annotations

from app.timefmt import now_iso

# Credits are USD-equivalent (app.billing): ten credits pay for $10 of work. Not a price.
BETA_CREDITS = 10.0


def _invite_key(email: str) -> str:
    return f"beta_invite:{email.strip().lower()}"


def mark_invited(db, email: str) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                  (_invite_key(email), now_iso()))


def pending_invite(db, email: str | None) -> bool:
    if not email:
        return False
    with db.tx() as c:
        return c.execute("SELECT 1 FROM meta WHERE key = ?", (_invite_key(email),)).fetchone() is not None


def invited_addresses(db) -> set[str]:
    with db.tx() as c:
        return {r[0][len("beta_invite:"):] for r in c.execute("SELECT key FROM meta WHERE key LIKE 'beta_invite:%'")}


def invite_email(api, to: str, name: str | None = None, existing: bool = False) -> bool:
    """Send the beta invite; False (and a log line) when it did not go."""
    from app.notify import templates
    base = api.settings.public_url
    try:
        api.email_sender.send(templates.email("beta_invite", to, public_url=base, name=name, credits=BETA_CREDITS,
                                              existing=existing, link=f"{base}/#{'home' if existing else 'login'}"))
        return True
    except Exception:  # noqa: BLE001 - the invite is recorded; the log says the email failed
        api.log.exception("beta invite email")
        return False
