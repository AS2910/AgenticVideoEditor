"""Launch item 9: every email has an HTML and a text version, in the Volt style;
user values are escaped; links stay on the public URL; no em dash; the
sender sends and keeps both parts; one failed job or spend alert in the
digest reads as its own email."""
import json
import re
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
import pytest

from app.notify import digest, email, templates
from app.store.db import Database

BASE = "https://app.voltage.example"
EVIL = '<script>alert("x")</script>'


def _links(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


@pytest.mark.parametrize("kind", templates.KINDS)
def test_each_email_renders_html_and_text_with_links_on_the_public_url(kind):
    r = templates.preview(kind, BASE)
    assert r.subject and r.text.strip() and r.html.startswith("<!doctype html>")
    assert "—" not in r.subject + r.text + r.html and "&mdash;" not in r.html
    assert "<table" in r.html and 'role="presentation"' in r.html and "<img" not in r.html
    assert "#D7FF3A" in r.html and "#0B0B0C" in r.html and "Voltage" in r.html
    links = _links(r.html)
    assert links and all(link.startswith(BASE + "/") for link in links), links
    for url in re.findall(r"https?://\S+", r.text):
        # The internal abuse report quotes the reported place as text (never as a link).
        assert url.startswith(BASE + "/") or kind == "abuse_report" and url not in links, url
    assert "\n--\n" in r.text                                  # the footer: why, and how to stop
    assert r.html.count("bgcolor=\"#D7FF3A\"") <= 1             # at most one button


def test_the_samples_cover_every_kind_and_the_waitlist_invite():
    assert set(templates.SAMPLES) == set(templates.KINDS) == set(templates.LABELS)
    for k in ("verify_email", "password_reset", "workspace_invite", "review_invite", "digest", "receipt", "invoice",
              "spend_alert", "job_failed", "account_deleted", "access_invite"):
        assert k in templates.KINDS


@pytest.mark.parametrize("kind", templates.KINDS)
def test_user_values_are_escaped(kind):
    data = {}
    for k, v in templates.SAMPLES[kind].items():
        if k in ("link", "threshold", "version", "subtotal", "cgst", "sgst", "igst", "total", "tax_kind", "test_mode", "currency"):
            data[k] = v
        elif isinstance(v, str):
            data[k] = EVIL
        elif isinstance(v, list):
            data[k] = [EVIL for _ in v]
        elif isinstance(v, dict):
            data[k] = {kk: EVIL for kk in v}
        else:
            data[k] = v
    r = templates.render(kind, public_url=BASE, **data)
    assert "<script>" not in r.html
    if EVIL in json.dumps(data, ensure_ascii=False).replace('\\"', '"'):
        assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in r.html


def test_a_link_off_the_public_url_becomes_the_app_home():
    for bad in ("https://evil.example/#reset/x", "javascript:alert(1)", "https://app.voltage.example.evil.example/x",
                "//evil.example/x", "http://app.voltage.example/x"):
        r = templates.render("password_reset", public_url=BASE, link=bad)
        for link in _links(r.html) + re.findall(r"https?://\S+", r.text):
            assert urlsplit(link).netloc == "app.voltage.example" and link.startswith("https://"), (bad, link)
        assert "javascript" not in r.html and "evil.example/#reset" not in r.text
    assert templates.own_link("#v/p1", BASE) == f"{BASE}/#v/p1"
    assert templates.own_link(f"{BASE}/api/auth/verify?token=a", BASE) == f"{BASE}/api/auth/verify?token=a"


def test_spend_alert_wording_follows_the_threshold():
    base = {"what": "your monthly ceiling", "used": "$25.00", "limit": "$50.00"}
    half, most, full = (templates.render("spend_alert", public_url=BASE, threshold=t, **base) for t in (50, 80, 100))
    assert half.subject == "You have used half of your monthly ceiling" and "Nothing has stopped" in half.text
    assert most.subject == "You have used 80% of your monthly ceiling" and "stop at 100%" in most.text
    assert full.subject == "You have reached your monthly ceiling" and "Paid steps stop until it is raised." in full.text
    member = templates.render("spend_alert", public_url=BASE, threshold=100, workspace=True, **{**base, "what": "its monthly ceiling"})
    assert member.subject == "This workspace has reached its monthly ceiling"
    credits = templates.render("spend_alert", public_url=BASE, threshold=100, credits=True, what="your credits", used="5", limit="5")
    assert "top up or pick a plan" in credits.text and "Top up" in credits.html


def test_receipt_and_invoice_carry_the_gst_lines():
    intra = {"number": "VLT-1", "issued": "2026-11-04", "description": "Top-up: 500 credits", "currency": "INR",
             "subtotal": 1000, "cgst": 90, "sgst": 90, "igst": 0, "total": 1180, "tax_kind": "intra"}
    r = templates.render("receipt", public_url=BASE, credits=500, **intra)
    assert "CGST 9%: ₹90.00" in r.text and "SGST 9%: ₹90.00" in r.text and "Total: ₹1,180.00" in r.text
    inter = templates.render("invoice", public_url=BASE, **{**intra, "tax_kind": "inter", "igst": 180, "cgst": 0, "sgst": 0},
                             buyer="Ann", place="Maharashtra", seller={"name": "Voltage Pvt Ltd", "gstin": "", "state": "29"})
    assert "IGST 18%: ₹180.00" in inter.text and "Seller GSTIN: not set yet" in inter.text and "From: Voltage Pvt Ltd" in inter.text
    export = templates.render("invoice", public_url=BASE, **{**intra, "tax_kind": "export", "currency": "USD", "cgst": 0, "sgst": 0,
                                                            "total": 1000}, buyer="Ann", place="US", seller={})
    assert "GST 0% (export of services): $0.00" in export.text
    test = templates.render("receipt", public_url=BASE, credits=1, test_mode=True, **intra)
    assert test.text.startswith("Test mode.")


def test_invoice_data_reads_a_billing_invoice_row():
    inv = {"number": "VLT-2", "issued_at": "2026-11-04T10:00:00Z", "description": "Creator plan", "currency": "INR",
           "subtotal": 100, "cgst": 9, "sgst": 9, "igst": 0, "total": 118, "tax_kind": "intra", "test_mode": 1,
           "owner": "acct:1", "legal_name": "", "gstin": "", "state_code": "29", "country": "IN"}
    d = templates.invoice_data(inv, {"name": "S", "gstin": "", "state": "29"}, {"29": "Karnataka"})
    assert d["place"] == "Karnataka" and d["buyer"] == "acct:1" and d["seller"]["state_name"] == "Karnataka"
    assert "Place of supply: Karnataka" in templates.render("invoice", public_url=BASE, **d).text


def test_account_deleted_says_what_was_removed_and_what_is_kept_for_how_long():
    removed, kept = templates.deletion_lists(7.0)
    r = templates.render("account_deleted", public_url=BASE, removed=removed, kept=kept)
    assert "for 7 years after deletion" in r.text and "invoices" in r.text and "Every video and project" in r.text


def test_footers_say_why_and_how_to_stop():
    assert "cannot be turned off" in templates.preview("verify_email", BASE).text
    for kind in ("digest", "spend_alert", "job_failed"):
        assert f"{templates.NOTIFY_STOP}{BASE}/#notifications" in templates.preview(kind, BASE).text


def test_access_invite_is_ready_for_the_waitlist():
    e = templates.email("access_invite", "ann@example.com", public_url=BASE, link="#login", name="Ann")
    assert e.kind == "access_invite" and e.html and e.body.startswith("Hi Ann,") and f"{BASE}/#login" in e.body


# ── the sender: both parts ───────────────────────────────────────────────────

def test_the_outbox_keeps_html_beside_the_text(tmp_path):
    db = Database(tmp_path / "t.db")
    sender = email.OutboxEmail(db)
    sender.send(templates.email("verify_email", "a@b.co", public_url=BASE, link="/api/auth/verify?token=t"))
    sender.send(email.Email(to="a@b.co", subject="Plain", body="Only text", kind="digest"))
    first, second = email.outbox(db)
    assert first["html"].startswith("<!doctype html>") and f"{BASE}/api/auth/verify?token=t" in first["body"]
    assert second["html"] is None


def test_resend_gets_both_parts(tmp_path):
    db = Database(tmp_path / "t.db")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"id": "e1"})
    sender = email.ResendEmail(db, "re_test", "Voltage <hi@voltage.example>", client=httpx.Client(transport=httpx.MockTransport(handler)))
    sender.send(templates.email("sign_in", "a@b.co", public_url=BASE, link=f"{BASE}/api/auth/email/callback?token=t"))
    assert seen[0]["text"].startswith("Hi,") and seen[0]["html"].startswith("<!doctype html>")
    assert email.outbox(db)[0]["html"] == seen[0]["html"]


# ── the digest: a lone failure or alert reads as its own email ──────────────

def _flush(db):
    return digest.flush(db, email.OutboxEmail(db), digest.utcnow() + timedelta(minutes=11), lambda o: "u@x.io",
                        lambda item: f"{BASE}/#v/p1", public_url=BASE)


def test_a_lone_failed_job_reads_as_the_job_failed_email(tmp_path):
    db = Database(tmp_path / "t.db")
    with db.tx() as c:
        digest.queue_in(c, "u", "job_failed", video_id="p1", payload={
            "text": "The export of ad.mp4 failed. ffmpeg stopped.",
            "email": {"template": "job_failed", "what": "The export", "name": "ad.mp4", "reason": "ffmpeg stopped.", "link": "#v/p1"}})
    [sent] = _flush(db)
    assert sent.kind == "digest" and sent.subject == "The export of ad.mp4 failed"
    assert "What happened: ffmpeg stopped." in sent.body and f"Open the video: {BASE}/#v/p1" in sent.body and sent.html


def test_a_lone_spend_alert_reads_as_the_spend_alert_email_and_two_items_as_the_digest(tmp_path):
    db = Database(tmp_path / "t.db")
    alert = {"text": "You have used 80% of your monthly ceiling ($8 of $10).",
             "email": {"template": "spend_alert", "threshold": 80, "what": "your monthly ceiling", "used": "$8", "limit": "$10",
                       "link": "#usage"}}
    with db.tx() as c:
        digest.queue_in(c, "u", "spend_alert", payload=alert)
    [sent] = _flush(db)
    assert sent.subject == "You have used 80% of your monthly ceiling" and f"{BASE}/#usage" in sent.body
    with db.tx() as c:
        digest.queue_in(c, "u", "spend_alert", payload=alert)
        digest.queue_in(c, "u", "job_done", payload={"text": "The export is done."})
    [both] = _flush(db)
    assert both.subject == "2 updates from Voltage" and "- You have used 80%" in both.body and "- The export is done." in both.body
