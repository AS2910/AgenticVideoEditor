"""Beta kit (the beta starts 28 October 2026).

    COHORT, COHORT_FLAGS, BETA_CREDITS
    join(db, flags, owner) -> {joined, granted}    into the cohort: its flags on, the credits once
    in_cohort(flags, owner) -> bool / cohort(db) -> [{owner, since}]
    claim(owner) -> bool                    at sign-in: an address invited to the beta joins
    survey_due(db, flags, person, owner) / survey_shown(...) / survey_answer(...)    the three questions
    pending_invite(db, email) / mark_invited(db, email)    a waitlist address invited to the beta
    invited_addresses(db) -> set            every address invited to the beta
    invite_email(api, to, name, existing)   the beta invite (templates `beta_invite`); never raises

A waitlist row's "Invite to beta" (landing_api) marks the row invited, as
Send invite does, and remembers the address in `meta` under
`beta_invite:{email}`, so the person joins the cohort when they first sign in.

The cohort is the flag `beta.cohort`, a row per person in `feature_flags`.
Joining also writes a row turning on each of COHORT_FLAGS for them (B1 batch
goals and B3 batch export are phase B, `projects.batch`; C2 the client review
link is phase C, `projects.review`; a phase is one flag, so B2 and C1 come
with them), so an admin can still turn one off per person on Features. The
credits are an admin grant (billing.admin_grant, reason "beta", never lapse),
given once per person: `meta` `beta_credits:{owner}` is written first, in
the same step that decides, so two joins at once grant once.
"""
from __future__ import annotations

import logging

from app.timefmt import now_iso

log = logging.getLogger("voltage.beta")

COHORT = "beta.cohort"
COHORT_FLAGS = ("projects.batch", "projects.review")
# Credits are USD-equivalent (app.billing): ten credits pay for $10 of work. Not a price.
BETA_CREDITS = 10.0
REASON = "beta"


def in_cohort(flags, owner: str | None) -> bool:
    return bool(owner) and flags.enabled(COHORT, owner)


def cohort(db) -> list[dict]:
    """Everyone in the cohort, with when they joined (their flag row's time), newest first."""
    with db.tx() as c:
        return [{"owner": r["owner"], "since": r["updated_at"]} for r in c.execute(
            "SELECT owner, updated_at FROM feature_flags WHERE flag = ? AND enabled = 1 AND owner <> '*' "
            "ORDER BY updated_at DESC, owner", (COHORT,))]


def _grant_once(db, owner: str) -> bool:
    from app import billing
    key = f"beta_credits:{owner}"
    with db.tx() as c:
        if c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                     (key, now_iso())).rowcount != 1:
            return False
    try:
        billing.admin_grant(db, owner, BETA_CREDITS, REASON)
    except Exception:
        with db.tx() as c:                  # not granted: the next join may try again
            c.execute("DELETE FROM meta WHERE key = ?", (key,))
        raise
    return True


def join(db, flags, owner: str) -> dict:
    """Into the cohort (again is harmless): the cohort flag and its flags on, the credits once."""
    joined = not in_cohort(flags, owner)
    if joined:
        flags.set(COHORT, owner, True)
        for flag in COHORT_FLAGS:
            flags.set(flag, owner, True)
    granted = _grant_once(db, owner)
    if joined:
        from app import analytics
        analytics.track("beta.joined", owner, {"granted": granted}, db=db)
    return {"joined": joined, "granted": granted, "credits": BETA_CREDITS if granted else 0.0}


def _api():
    from app.api import main
    return main


def claim(owner: str) -> bool:
    """At sign-in: someone whose address was invited to the beta joins the cohort. Never raises."""
    api = _api()
    try:
        from app import admin
        if in_cohort(api.flags, owner) or not any(pending_invite(api.database, e) for e in admin.emails_of(api.database, owner)):
            return False
        join(api.database, api.flags, owner)
        log.warning("%s joined the beta from an invite", owner)
        return True
    except Exception:  # noqa: BLE001 - sign-in never fails over the beta
        log.exception("beta claim for %s", owner)
        return False


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


# ── the three questions after a first export (migration 0042) ─────────────────

QUESTIONS = (
    {"id": "useful", "text": "How useful was Voltage for this video?",
     "choices": [["very", "Very useful"], ["somewhat", "Somewhat useful"], ["not", "Not useful"]]},
    {"id": "almost_stopped", "text": "What almost stopped you?", "optional": True},
    {"id": "would_pay", "text": "Would you pay for Voltage?", "choices": [["yes", "Yes"], ["maybe", "Maybe"], ["no", "No"]]},
)
USEFUL = ("very", "somewhat", "not")
WOULD_PAY = ("yes", "maybe", "no")
MAX_WORDS = 2000
THANKS = "Thank you. That helps us more than you know."


class SurveyDone(ValueError):
    """The questions were answered already."""


def exported(db, *owners: str) -> bool:
    """Whether any of `owners` has exported: the funnel's first export, or the Export page opened
    (the onboarding checklist's `export`, ticked when the page shows the file)."""
    import json
    with db.tx() as c:
        for owner in owners:
            if c.execute("SELECT 1 FROM analytics_events WHERE name = 'first_export' AND owner = ? LIMIT 1", (owner,)).fetchone():
                return True
            row = c.execute("SELECT value FROM meta WHERE key = ?", (f"onboarding:{owner}",)).fetchone()
            if row and "export" in (json.loads(row[0] or "{}").get("checklist") or []):
                return True
    return False


def survey_row(db, person: str) -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM beta_survey WHERE owner = ?", (person,)).fetchone()
    return dict(r) if r else None


def survey_due(db, flags, person: str, owner: str) -> bool:
    """Shown once: to someone in the cohort, after their first export, never again once shown."""
    return in_cohort(flags, owner) and survey_row(db, person) is None and exported(db, owner, person)


def survey_shown(db, person: str, workspace_id: str | None, video_id: str | None) -> bool:
    """Record that the questions were put; True the first time."""
    with db.tx() as c:
        return c.execute("INSERT INTO beta_survey (owner, workspace_id, video_id, shown_at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (owner) DO NOTHING", (person, workspace_id, video_id, now_iso())).rowcount == 1


def survey_answer(db, person: str, workspace_id: str | None, useful: str, almost_stopped: str | None,
                  would_pay: str, video_id: str | None = None) -> dict:
    if useful not in USEFUL or would_pay not in WOULD_PAY:
        raise ValueError("Pick one answer for the first and the last question.")
    words = " ".join((almost_stopped or "").split())[:MAX_WORDS] or None
    survey_shown(db, person, workspace_id, video_id)
    with db.tx() as c:
        done = c.execute("UPDATE beta_survey SET useful = ?, almost_stopped = ?, would_pay = ?, answered_at = ? "
                         "WHERE owner = ? AND answered_at IS NULL", (useful, words, would_pay, now_iso(), person)).rowcount
    if done != 1:
        raise SurveyDone("You answered these already. Thank you.")
    return survey_row(db, person) or {}

