"""Launch item 9: every email Voltage sends, in the Volt style, as HTML and plain text.

    render(kind, public_url=..., **data) -> Rendered(subject, text, html)
    email(kind, to, public_url=..., owner=, workspace_id=, sent_as=, **data) -> Email (both bodies)
    preview(kind, public_url) -> Rendered    sample data, for the admin preview page
    KINDS, LABELS, SAMPLES

The HTML is what mail clients can draw: tables for layout, inline CSS, a
system font stack, the Volt colours (paper #F3F3EF, white card, ink
#0B0B0C, one volt #D7FF3A button with ink text), a text wordmark (no remote
images) and a plain footer that says why the email came and how to stop the
ones that are not essential. Every value from a person is HTML-escaped, and
every link points at the app's own public URL (AVE_PUBLIC_URL): a link that
does not is replaced by the app's home.

The text version carries the same words and each link on its own line.

Item 8 (the waitlist) sends its access invite with
`templates.email("access_invite", to, public_url=..., link=..., name=...)`.
"""
from __future__ import annotations

import html as _html
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.notify.email import Email

PAPER, CARD, INK, VOLT, LINE, MUTED = "#F3F3EF", "#FFFFFF", "#0B0B0C", "#D7FF3A", "#DEDED6", "#5C5C58"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
DEFAULT_URL = "http://localhost:5173"

# Why an account email cannot be turned off, said the same way everywhere.
ACCOUNT_STOP = "This is an account email, so it cannot be turned off."
NOTIFY_STOP = "To stop these, turn off email for them in Voltage: "


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


@dataclass
class _Mail:
    subject: str
    heading: str
    paras: list[str] = field(default_factory=list)
    rows: list[tuple[str, str]] = field(default_factory=list)     # label, value (a table)
    items: list[str] = field(default_factory=list)                # a bulleted list
    button: tuple[str, str] | None = None                         # label, link
    after: list[str] = field(default_factory=list)
    reason: str = ""
    stop: str = ACCOUNT_STOP
    stop_link: str | None = None                                  # a link after the stop sentence
    banner: str | None = None                                     # e.g. test mode
    greeting: str | None = "Hi,"


def own_link(link: str | None, public_url: str) -> str:
    """`link` when it is on the app's public URL (a hash or path is put on it); else the app's home."""
    base = (public_url or DEFAULT_URL).rstrip("/")
    link = (link or "").strip()
    if link.startswith(("#", "/")):
        return f"{base}/{link.lstrip('/')}"
    if link == base or link.startswith((base + "/", base + "#")):
        b, u = urlsplit(base), urlsplit(link)
        if (b.scheme, b.netloc) == (u.scheme, u.netloc):
            return link
    return f"{base}/"


def _money(amount: float, currency: str) -> str:
    return f"₹{amount:,.2f}" if (currency or "").upper() == "INR" else f"${amount:,.2f}"


# ── the layout ──────────────────────────────────────────────────────────────

def _e(s: object) -> str:
    return _html.escape(str(s), quote=True)


def _p(text: str, size: int = 15, color: str = INK, extra: str = "") -> str:
    return (f'<p style="margin:0 0 14px 0;font-family:{FONT};font-size:{size}px;line-height:1.55;color:{color};{extra}">'
            f"{_e(text)}</p>")


def _to_html(m: _Mail, public_url: str) -> str:
    base = (public_url or DEFAULT_URL).rstrip("/")
    parts: list[str] = []
    if m.banner:
        parts.append(f'<p style="margin:0 0 18px 0;padding:8px 12px;border:1.5px solid {INK};background:#FFB020;'
                     f'font-family:{FONT};font-size:14px;font-weight:700;color:{INK};">{_e(m.banner)}</p>')
    parts.append(f'<h1 style="margin:0 0 16px 0;font-family:{FONT};font-size:24px;line-height:1.25;font-weight:700;'
                 f'letter-spacing:-0.02em;color:{INK};">{_e(m.heading)}</h1>')
    if m.greeting:
        parts.append(_p(m.greeting))
    parts += [_p(t) for t in m.paras]
    if m.items:
        lis = "".join(f'<li style="margin:0 0 8px 0;">{_e(i)}</li>' for i in m.items)
        parts.append(f'<ul style="margin:0 0 16px 0;padding:0 0 0 20px;font-family:{FONT};font-size:15px;line-height:1.5;color:{INK};">{lis}</ul>')
    if m.rows:
        trs = "".join(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid {LINE};font-family:{FONT};font-size:14px;color:{INK};">{_e(k)}</td>'
            f'<td align="right" style="padding:8px 0;border-bottom:1px solid {LINE};font-family:{FONT};font-size:14px;font-variant-numeric:tabular-nums;color:{INK};">{_e(v)}</td></tr>'
            for k, v in m.rows)
        parts.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                     f'style="border-collapse:collapse;margin:0 0 18px 0;">{trs}</table>')
    if m.button:
        label, link = m.button
        url = _e(own_link(link, base))
        parts.append(
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 18px 0;"><tr>'
            f'<td bgcolor="{VOLT}" style="background:{VOLT};border:1.5px solid {INK};border-radius:6px;box-shadow:4px 4px 0 {INK};">'
            f'<a href="{url}" target="_blank" rel="noopener" style="display:inline-block;padding:12px 22px;font-family:{FONT};'
            f'font-size:15px;font-weight:700;color:{INK};text-decoration:none;">{_e(label)}</a></td></tr></table>'
            f'<p style="margin:0 0 14px 0;font-family:{FONT};font-size:13px;line-height:1.5;color:{MUTED};">'
            f'If the button does not work, copy this link into your browser:<br>'
            f'<a href="{url}" style="color:{INK};word-break:break-all;">{url}</a></p>')
    parts += [_p(t, 14, MUTED) for t in m.after]
    stop = _e(m.stop)
    if m.stop_link:
        link = _e(own_link(m.stop_link, base))
        stop += f'<a href="{link}" style="color:{MUTED};">{link}</a>'
    footer = (f'<p style="margin:0 0 6px 0;">{_e(m.reason)}</p>' if m.reason else "") + f'<p style="margin:0 0 6px 0;">{stop}</p>' \
        + f'<p style="margin:0;">Voltage &middot; <a href="{_e(base)}/" style="color:{MUTED};">{_e(urlsplit(base).netloc or base)}</a></p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{_e(m.subject)}</title></head>
<body style="margin:0;padding:0;background:{PAPER};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAPER};">{_e(m.paras[0] if m.paras else m.heading)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAPER}" style="background:{PAPER};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
<tr><td style="padding:0 0 16px 2px;font-family:{FONT};font-size:22px;font-weight:700;letter-spacing:-0.02em;color:{INK};">
<span style="display:inline-block;padding:2px 8px;background:{VOLT};border:1.5px solid {INK};">Voltage</span></td></tr>
<tr><td bgcolor="{CARD}" style="background:{CARD};border:1.5px solid {INK};border-radius:12px;padding:28px 28px 14px 28px;">
{"".join(parts)}
</td></tr>
<tr><td style="padding:18px 4px 0 4px;font-family:{FONT};font-size:12px;line-height:1.5;color:{MUTED};">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def _to_text(m: _Mail, public_url: str) -> str:
    base = (public_url or DEFAULT_URL).rstrip("/")
    out: list[str] = []
    if m.banner:
        out += [m.banner, ""]
    if m.greeting:
        out += [m.greeting, ""]
    for t in m.paras:
        out += [t, ""]
    if m.items:
        out += [f"- {i}" for i in m.items] + [""]
    if m.rows:
        out += [f"{k}: {v}" for k, v in m.rows] + [""]
    if m.button:
        out += [f"{m.button[0]}: {own_link(m.button[1], base)}", ""]
    for t in m.after:
        out += [t, ""]
    out += ["--"]
    if m.reason:
        out.append(m.reason)
    out.append(m.stop + (own_link(m.stop_link, base) if m.stop_link else ""))
    return "\n".join(out)


# ── the emails ──────────────────────────────────────────────────────────────

def _verify_email(d: dict) -> _Mail:
    return _Mail("Confirm your email for Voltage", "Confirm your email",
                 ["Open this link to confirm your address and sign in. It works once, for 48 hours."],
                 button=("Confirm my email", d["link"]), after=["If you did not sign up, you can ignore this email."],
                 reason="You got this because someone signed up for Voltage with this address.")


def _password_reset(d: dict) -> _Mail:
    return _Mail("Reset your Voltage password", "Choose a new password",
                 ["Open this link to choose a new password. It works once, for one hour."],
                 button=("Choose a new password", d["link"]),
                 after=["If you did not ask for it, you can ignore this email; your password stays as it is."],
                 reason="You got this because someone asked to reset the password of the Voltage account on this address.")


def _account_exists(d: dict) -> _Mail:
    return _Mail("Someone tried to sign up with your address", "You already have an account",
                 ["Someone (perhaps you) tried to make a Voltage account with this address, which already has one.",
                  "To sign in, or reset your password, go to the sign-in page."],
                 button=("Go to sign-in", d.get("link") or "#login"), after=["If it was not you, you can ignore this email."],
                 reason="You got this because someone tried to sign up for Voltage with this address.")


def _change_email(d: dict) -> _Mail:
    return _Mail("Confirm your new email for Voltage", "Confirm your new address",
                 ["Open this link to make this your Voltage address. It works once, for 24 hours."],
                 button=("Use this address", d["link"]), after=["If you did not ask for this, you can ignore this email."],
                 reason="You got this because someone asked to move a Voltage account to this address.")


def _change_email_notice(d: dict) -> _Mail:
    return _Mail("Your Voltage address is changing", "Your address is changing",
                 [f"Someone signed in to your account asked to change its address to {d['new_address']}.",
                  "If it was not you, reset your password now and the change will not go through."],
                 button=("Go to sign-in", d.get("link") or "#login"),
                 reason="You got this because this address is the one on your Voltage account.")


def _sign_in(d: dict) -> _Mail:
    return _Mail("Your Voltage sign-in link", "Sign in to Voltage",
                 ["Open this link to sign in to Voltage. It works once, for 15 minutes."],
                 button=("Sign in", d["link"]), after=["If you did not ask for it, you can ignore this email."],
                 reason="You got this because someone asked to sign in to Voltage with this address.")


def _workspace_invite(d: dict) -> _Mail:
    word = d["role"]
    a = "an" if word[:1].lower() in "aeiou" else "a"
    who = f"{d['inviter']} invited you" if d.get("inviter") else "You have been invited"
    return _Mail("You are invited to a Voltage workspace", "Join a Voltage workspace",
                 [f"{who} to a Voltage workspace as {a} {word}, so you can {d['can']}."],
                 button=("Accept the invite", d["link"]), after=[f"The link works until {d['expires']}."],
                 reason="You got this because someone in a Voltage workspace invited this address.",
                 stop="If you do not want to join, ignore this email; nothing more will come about this invite.")


def _review_invite(d: dict) -> _Mail:
    return _Mail(f"Please review {d['title']}", f"Please review {d['title']}",
                 [(f"You have been asked to review {d['title']}. Watch it, leave comments at the moment they are about, "
                   "then approve it or ask for changes. No account needed.")],
                 button=("Open the review", d["link"]), after=[f"The link works until {d['expires']}."],
                 reason="You got this because someone using Voltage shared a video with this address for review.",
                 stop="Emails about this review stop when the link expires or is closed.",
                 greeting=f"Hi {d['name']}," if d.get("name") else "Hi,")


def _version_ready(d: dict) -> _Mail:
    v, f = d["version"], d["filename"]
    return _Mail(f"v{v} of {f} is ready to review", "A new version is ready",
                 [f"A new version (v{v}) of {f} is ready. The review page shows what changed since the last one."],
                 button=("Open the review", d["link"]),
                 reason="You got this because you are reviewing this video in Voltage.",
                 stop="Emails about this review stop when the link expires or is closed.",
                 greeting=f"Hi {d['name']}," if d.get("name") else "Hi,")


def _digest(d: dict) -> _Mail:
    reviewers = d.get("reviewers", True)
    return _Mail(d.get("subject") or "Updates from Voltage", "What your reviewers said" if reviewers else "What happened in Voltage",
                 [d.get("intro") or ("Here is what your reviewers said." if reviewers else "Here is what happened in Voltage.")],
                 items=list(d["items"]), button=("Open the project", d["link"]) if d.get("link") else None,
                 reason="You got this because you asked Voltage to email you about these. News waits ten minutes and comes in one email.",
                 stop=NOTIFY_STOP, stop_link="#notifications", greeting=None)


def _money_rows(d: dict) -> list[tuple[str, str]]:
    cur = d.get("currency", "INR")
    rows = [(d["description"], _money(float(d["subtotal"]), cur))]
    kind = d.get("tax_kind")
    if kind == "intra":
        rows += [("CGST 9%", _money(float(d["cgst"]), cur)), ("SGST 9%", _money(float(d["sgst"]), cur))]
    elif kind == "inter":
        rows += [("IGST 18%", _money(float(d["igst"]), cur))]
    else:
        rows += [("GST 0% (export of services)", _money(0, cur))]
    return rows + [("Total", _money(float(d["total"]), cur))]


def _test_banner(d: dict) -> str | None:
    return "Test mode. No money moved; this is a sample of what a real one will look like." if d.get("test_mode") else None


def _receipt(d: dict) -> _Mail:
    return _Mail(f"Your Voltage receipt {d['number']}", "Thanks, your top-up is in",
                 [f"We added {d['credits']} credits to your account. Here is your receipt."],
                 rows=[("Receipt", d["number"]), ("Paid on", d["issued"]), *_money_rows(d)],
                 button=("See your billing", d.get("link") or "#billing"),
                 after=["Your tax invoice is on the Billing page."],
                 reason="You got this because you paid for a Voltage top-up.", banner=_test_banner(d))


def _invoice(d: dict) -> _Mail:
    s = d["seller"]
    rows = [("Invoice", d["number"]), ("Issued", d["issued"]),
            ("From", s.get("name") or "Voltage (seller details not set)"), ("Seller GSTIN", s.get("gstin") or "not set yet"),
            ("Seller state", s.get("state_name") or s.get("state") or ""),
            ("To", d["buyer"]), ("Buyer GSTIN", d.get("buyer_gstin") or "No GSTIN"), ("Place of supply", d["place"]),
            ("SAC", d.get("sac") or "998314"), *_money_rows(d)]
    return _Mail(f"Your Voltage invoice {d['number']}", "Your tax invoice",
                 [f"Here is the tax invoice for {d['description']}. A printable copy is on the Billing page."],
                 rows=rows, button=("See the invoice", d.get("link") or "#billing"),
                 reason="You got this because you paid for Voltage.", banner=_test_banner(d))


def _spend_alert(d: dict) -> _Mail:
    hit = int(d["threshold"])
    who = "This workspace has" if d.get("workspace") else "You have"
    what = d["what"]
    if hit >= 100:
        subject = f"{who} reached {what}"
        first = (f"{who} used all of {what}." if d.get("credits") else f"{who} reached {what} ({d['limit']}).")
        then = (d.get("stops") or ("Paid steps are paused until you top up or pick a plan." if d.get("credits")
                                   else "Paid steps stop until it is raised."))
        button = ("Top up" if d.get("credits") else "Raise the ceiling")
    else:
        part = "half" if hit == 50 else f"{hit}%"
        subject = f"{who} used {part} of {what}"
        first = f"{who} used {hit}% of {what} ({d['used']} of {d['limit']})."
        then = ("Nothing has stopped. This is a heads-up." if hit == 50
                else "Paid steps stop at 100%, so now is a good time to raise it if you need more.")
        button = ("See your credits" if d.get("credits") else "See the spend")
    return _Mail(subject, f"{hit}% of {what}" if hit < 100 else subject, [first, then],
                 button=(button, d.get("link") or "#usage"),
                 reason=f"You got this because spend reached {hit}% of a ceiling in Voltage. Each one is said once.",
                 stop=NOTIFY_STOP, stop_link="#notifications")


def _job_failed(d: dict) -> _Mail:
    of = f" of {d['name']}" if d.get("name") else ""
    reason = (d.get("reason") or "").strip() or "Voltage did not say why."
    return _Mail(f"{d['what']}{of} failed", f"{d['what']}{of} failed",
                 [f"{d['what']}{of} stopped before it finished.", f"What happened: {reason}",
                  "Nothing you made before it is lost. Open the video to try again."],
                 button=("Open the video", d.get("link") or "#home"),
                 reason="You got this because you asked Voltage to email you when work fails.",
                 stop=NOTIFY_STOP, stop_link="#notifications")


def _account_deleted(d: dict) -> _Mail:
    return _Mail("Your Voltage account is deleted", "Your account is deleted",
                 ["We deleted your Voltage account, as you asked. This is the last email about it.",
                  "What we removed:"],
                 items=list(d["removed"]),
                 after=["What we keep, and for how long:", *[f"- {k}" for k in d["kept"]],
                        "If you did not ask for this, write to us at the address on the Privacy page."],
                 reason="You got this because the Voltage account on this address was deleted.",
                 stop="Nothing more will come from Voltage to this address.")


def _access_invite(d: dict) -> _Mail:
    after = [f"The link works until {d['expires']}."] if d.get("expires") else []
    return _Mail("Your Voltage access is ready", "You are in",
                 [("Thanks for waiting. Your spot on Voltage is ready: make an account, upload a video, "
                   "and tell Voltage what to change.")],
                 button=("Make my account", d["link"]), after=after + ["If you did not join the waitlist, you can ignore this email."],
                 reason="You got this because this address joined the Voltage waitlist.",
                 stop="This is the one email the waitlist sends, so there is nothing to turn off.",
                 greeting=f"Hi {d['name']}," if d.get("name") else "Hi,")


def _abuse_report(d: dict) -> _Mail:
    return _Mail(d["title"], d["title"], [],
                 rows=[("Where", d.get("location") or "(none)"), ("Details", d.get("details") or "(none)"),
                       ("Contact", d.get("contact") or "(none)")],
                 button=("Open admin", "#admin"),
                 reason="You got this because this address takes Voltage's trust and safety reports.",
                 stop="Change AVE_TRUST_EMAIL to send these somewhere else.", greeting=None)


_BUILD: dict[str, Callable[[dict], _Mail]] = {
    "verify_email": _verify_email, "password_reset": _password_reset, "account_exists": _account_exists,
    "change_email": _change_email, "change_email_notice": _change_email_notice, "sign_in": _sign_in,
    "workspace_invite": _workspace_invite, "review_invite": _review_invite, "version_ready": _version_ready,
    "digest": _digest, "receipt": _receipt, "invoice": _invoice, "spend_alert": _spend_alert,
    "job_failed": _job_failed, "account_deleted": _account_deleted, "access_invite": _access_invite,
    "abuse_report": _abuse_report,
}
KINDS = tuple(_BUILD)
LABELS = {
    "verify_email": "Verify address", "password_reset": "Password reset", "account_exists": "Sign-up with a taken address",
    "change_email": "Change email: confirm", "change_email_notice": "Change email: notice to the old address",
    "sign_in": "Sign-in link", "workspace_invite": "Workspace invite", "review_invite": "Review link",
    "version_ready": "Review: new version", "digest": "Review comment digest", "receipt": "Receipt (top-up)",
    "invoice": "Invoice (GST)", "spend_alert": "Spend alert", "job_failed": "Job failed",
    "account_deleted": "Account deleted", "access_invite": "Access invite (waitlist)", "abuse_report": "Abuse report (internal)",
}


def render(kind: str, *, public_url: str | None = None, **data) -> Rendered:
    if kind not in _BUILD:
        raise KeyError(f"no email template {kind!r}")
    base = (public_url or DEFAULT_URL).rstrip("/")
    m = _BUILD[kind](data)
    return Rendered(m.subject, _to_text(m, base), _to_html(m, base))


def email(kind: str, to: str, *, public_url: str | None = None, owner: str | None = None,
          workspace_id: str | None = None, sent_as: str | None = None, **data) -> Email:
    """The Email for `kind`, with both bodies; `sent_as` keeps an older outbox kind (the digest)."""
    r = render(kind, public_url=public_url, **data)
    return Email(to=to, subject=r.subject, body=r.text, html=r.html, kind=sent_as or kind, owner=owner, workspace_id=workspace_id)


# ── what an account deletion removes and keeps (from DELETE /account) ──────

def deletion_lists(consent_years: float) -> tuple[list[str], list[str]]:
    years = f"{consent_years:g} year" + ("" if consent_years == 1 else "s")
    removed = ["Every video and project, with its media, takes and exports",
               "The voices made for your videos, and your own voices (deleted at the voice service too)",
               "Your samples, defaults, templates and pins", "Your sign-in and password"]
    kept = [f"Consent records for voices, for {years} after deletion, as the law asks",
            "Your invoices, for as long as tax law asks",
            "A note that you asked for this deletion, and when"]
    return removed, kept


def invoice_data(inv: dict, seller: dict, states: dict[str, str] | None = None) -> dict:
    """A billing invoice row (billing.invoice) as the receipt or invoice template's data."""
    states = states or {}
    return {
        "number": inv["number"], "issued": str(inv["issued_at"])[:10], "description": inv["description"],
        "currency": inv["currency"], "subtotal": inv["subtotal"], "cgst": inv["cgst"], "sgst": inv["sgst"],
        "igst": inv["igst"], "total": inv["total"], "tax_kind": inv["tax_kind"], "test_mode": bool(inv.get("test_mode")),
        "buyer": inv.get("legal_name") or inv["owner"], "buyer_gstin": inv.get("gstin") or "",
        "place": states.get(inv.get("state_code") or "", inv.get("country") or "Outside India"),
        "seller": {**seller, "state_name": states.get(seller.get("state") or "", seller.get("state") or "")},
    }


# ── the preview page's sample data ──────────────────────────────────────────

_REMOVED, _KEPT = deletion_lists(7.0)
_INV = {"number": "VLT-202611-00042", "issued": "2026-11-04", "description": "Top-up: 500 credits", "currency": "INR",
        "subtotal": 1000.0, "cgst": 90.0, "sgst": 90.0, "igst": 0.0, "total": 1180.0, "tax_kind": "intra", "test_mode": True}
SAMPLES: dict[str, dict] = {
    "verify_email": {"link": "/api/auth/verify?token=sample"},
    "password_reset": {"link": "#reset/sample"},
    "account_exists": {"link": "#login"},
    "change_email": {"link": "/api/auth/change-email/confirm?token=sample"},
    "change_email_notice": {"new_address": "ann@new.example"},
    "sign_in": {"link": "/api/auth/email/callback?token=sample"},
    "workspace_invite": {"role": "Editor", "can": "edit videos and projects", "link": "#invite/sample", "expires": "2026-11-11"},
    "review_invite": {"name": "Priya", "title": "Diwali promo", "link": "#s/sample", "expires": "2026-11-18"},
    "version_ready": {"name": "Priya", "filename": "promo.mp4", "version": 3, "link": "#s/sample"},
    "digest": {"subject": "3 updates from your reviewers", "link": "#p/f1", "items": [
        'Priya commented on promo.mp4 at 0:12 (v4): "Bigger logo"', "Priya approved promo.mp4 v4.",
        'Sam asked for changes on teaser.mp4 v2: "Shorter, please"']},
    "receipt": {**_INV, "credits": 500},
    "invoice": {**_INV, "description": "Creator plan, one month", "buyer": "Ann Studio LLP", "buyer_gstin": "29ABCDE1234F1Z5",
                "place": "Karnataka", "seller": {"name": "Voltage (seller details not set)", "gstin": "", "state": "29",
                                                 "state_name": "Karnataka"}},
    "spend_alert": {"threshold": 80, "what": "your monthly ceiling", "used": "$40.00", "limit": "$50.00", "link": "#usage"},
    "job_failed": {"what": "The export", "name": "promo.mp4", "reason": "ffmpeg stopped: the disk is full.", "link": "#v/p12"},
    "account_deleted": {"removed": _REMOVED, "kept": _KEPT},
    "access_invite": {"name": "Ann", "link": "#login", "expires": "2026-11-18"},
    "abuse_report": {"title": "Abuse report #7: Impersonation.", "location": "https://voltage.example/#s/abc",
                     "details": "Uses my voice without asking.", "contact": "me@example.com"},
}


def preview(kind: str, public_url: str | None = None) -> Rendered:
    return render(kind, public_url=public_url, **SAMPLES[kind])
