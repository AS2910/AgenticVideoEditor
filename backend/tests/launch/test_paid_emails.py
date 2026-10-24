"""Run 4 item 4b: the receipt, the tax invoice (with a PDF) and the
account-deleted email go out through their templates. A purchase through the
fake provider, Razorpay's signed payment and a Stripe webhook each send a
receipt and an invoice once; the PDF is a valid PDF 1.4 with the GST split;
deleting the account sends the last email. Every email lands in the fake outbox."""
import hashlib
import hmac
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.billing import pdf
from app.notify import email as email_mod
from tests.golive.test_item7_providers import RZP_SECRET, _session_event, live, ok, stripe_sig  # noqa: F401 - the fixture

ANN = "ann@example.com"


@pytest.fixture(autouse=True)
def clean():
    main.repo.reset()
    with main.database.tx() as c:
        c.execute("DELETE FROM notify_outbox WHERE to_addr = ?", (ANN,))
    email_mod.remember_address(main.database, "local", ANN)
    yield
    main.repo.reset()
    main.flags.clear("golive.g3", "local")


def _sent(kind: str) -> list[dict]:
    return email_mod.outbox(main.database, kind=kind, to=ANN)


def _check_pdf(data: bytes, *must: str) -> None:
    """A structural check (pypdf is not installed here): the header, every object the
    xref names at its offset, the trailer, and the words drawn on the page."""
    assert data.startswith(b"%PDF-1.4\n") and data.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)\n", data).group(1))
    assert data[start:start + 4] == b"xref"
    count = int(re.match(rb"xref\n0 (\d+)\n", data[start:]).group(1))
    entries = re.findall(rb"(\d{10}) (\d{5}) n \n", data[start:])
    assert len(entries) == count - 1
    for n, (offset, _gen) in enumerate(entries, start=1):
        assert data[int(offset):].startswith(b"%d 0 obj" % n), n
    stream = re.search(rb"/Length (\d+) >>\nstream\n", data)
    length = int(stream.group(1))
    assert data[stream.end() + length:].startswith(b"\nendstream")
    drawn = b" ".join(re.findall(rb"\((.*?)(?<!\\)\) Tj", data)).decode("latin-1")
    text = re.sub(r"\\(.)", r"\1", drawn)                    # the string escapes undone
    for words in must:
        assert words in text, words
    try:
        import pypdf
    except ImportError:
        return
    import io
    page = pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()
    for words in must:
        assert words in page


def test_a_fake_provider_top_up_sends_a_receipt_and_an_invoice_with_its_pdf():
    client = TestClient(main.app)
    client.put("/billing/details", json={"country": "IN", "legal_name": "Ann (Studio) LLP", "gstin": "29ABCDE1234F1Z5"})
    got = client.post("/billing/topup", json={"credits": 10})
    assert got.status_code == 200, got.text
    inv = got.json()["invoice"]
    [receipt], [invoice] = _sent("receipt"), _sent("invoice")
    assert receipt["subject"] == f"Your Voltage receipt {inv['number']}" and "We added 10 credits" in receipt["body"]
    assert "CGST 9%" in receipt["body"] and "Test mode" in receipt["body"]
    assert invoice["subject"] == f"Your Voltage invoice {inv['number']}" and "The PDF is attached" in invoice["body"]
    assert "Taxable value" in invoice["body"] and "29ABCDE1234F1Z5" in invoice["body"]
    [attached] = invoice["attachments"]
    assert attached.filename == f"{inv['number']}.pdf" and attached.content_type == "application/pdf"
    money = lambda v: f"INR {v:,.2f}"  # noqa: E731
    _check_pdf(attached.data, "Tax invoice", inv["number"], "Ann (Studio) LLP", "Taxable value", "CGST 9%", "SGST 9%",
               money(inv["subtotal"]), money(inv["cgst"]), money(inv["total"]), "Test mode")
    assert inv["cgst"] + inv["sgst"] == pytest.approx(round(inv["subtotal"] * 0.18, 2))


def test_a_plan_says_the_plan_and_another_state_is_igst():
    client = TestClient(main.app)
    client.put("/billing/details", json={"country": "IN", "state_code": "27"})       # Maharashtra; the seller is elsewhere
    inv = client.post("/billing/plan", json={"plan": "studio"}).json()["invoice"]
    assert inv["tax_kind"] == "inter"
    [receipt], [invoice] = _sent("receipt"), _sent("invoice")
    assert "You are on the Studio plan." in receipt["body"] and "Thanks, your plan is on" in receipt["html"]
    assert "IGST 18%" in invoice["body"] and "CGST" not in invoice["body"]
    _check_pdf(invoice["attachments"][0].data, "IGST 18%", f"INR {inv['igst']:,.2f}", "Place of supply: Maharashtra")


def test_outside_india_is_zero_rated_in_dollars():
    client = TestClient(main.app)
    inv = client.post("/billing/topup", json={"credits": 10}).json()["invoice"]
    assert inv["tax_kind"] == "export"
    _check_pdf(_sent("invoice")[0]["attachments"][0].data, "GST 0% (export of services)", f"USD {inv['total']:,.2f}")


def test_no_address_no_email_and_the_payment_still_goes_through():
    with main.database.tx() as c:
        c.execute("DELETE FROM meta WHERE key = 'notify_email:local'")
    got = TestClient(main.app).post("/billing/topup", json={"credits": 10})
    assert got.status_code == 200 and got.json()["invoice"]
    assert _sent("receipt") == []


def test_razorpay_signed_payment_emails_once_with_its_webhook(live):
    email_mod.remember_address(main.database, "local", ANN)
    client = TestClient(main.app)
    client.put("/billing/details", json={"country": "IN", "state_code": "29"})
    live.answers = [ok({"id": "order_mail"})]
    started = client.post("/billing/topup", json={"credits": 10}).json()
    assert _sent("receipt") == []                                     # nothing until it is paid
    sig = hmac.new(RZP_SECRET.encode(), b"order_mail|pay_9", hashlib.sha256).hexdigest()
    assert client.post("/billing/razorpay/verify", json={"order_id": "order_mail", "payment_id": "pay_9", "signature": sig}).status_code == 200
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_9", "order_id": "order_mail", "amount": started["checkout"]["client"]["amount"], "currency": "INR"}}}}
    body = json.dumps(event).encode()
    from tests.golive.test_item7_providers import rzp_sig
    client.post("/billing/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": rzp_sig(body), "X-Razorpay-Event-Id": "ev_m"})
    assert len(_sent("receipt")) == 1 and len(_sent("invoice")) == 1


def test_a_stripe_webhook_emails_once(live):
    email_mod.remember_address(main.database, "local", ANN)
    client = TestClient(main.app)
    live.answers = [ok({"id": "cs_mail", "url": "https://checkout.stripe.com/c/cs_mail"})]
    client.post("/billing/topup", json={"credits": 10})
    body = json.dumps(_session_event("evt_mail", session="cs_mail")).encode()
    headers = {"Stripe-Signature": stripe_sig(body), "Content-Type": "application/json"}
    assert client.post("/billing/webhooks/stripe", content=body, headers=headers).json()["handled"]
    assert client.post("/billing/webhooks/stripe", content=body, headers=headers).json()["duplicate"]
    [receipt] = _sent("receipt")
    assert "We added 10 credits" in receipt["body"] and len(_sent("invoice")) == 1


def test_the_pdf_escapes_and_stays_latin1():
    inv = {"number": "VLT-1", "issued_at": "2026-10-24T00:00:00Z", "provider": "fake", "checkout_id": "c1", "owner": "acct:1",
           "legal_name": "Ann (Studio) \\ ₹ Films", "gstin": "", "state_code": None, "country": "US", "description": "Top-up",
           "currency": "USD", "subtotal": 12.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 12.0, "tax_kind": "export",
           "test_mode": False}
    data = pdf.invoice_pdf(inv, {"name": "Voltage", "gstin": "", "state": "29"})
    _check_pdf(data, "Ann (Studio) \\ ? Films", "Place of supply: US", "USD 12.00")
    assert b"Test mode" not in data


def test_deleting_the_account_sends_the_last_email():
    assert TestClient(main.app).delete("/account").status_code == 204
    [gone] = _sent("account_deleted")
    assert gone["subject"] == "Your Voltage account is deleted"
    assert "What we removed:" in gone["body"] and "Consent records for voices" in gone["body"]


def test_resend_carries_the_attachment(tmp_path):
    from app.store.db import Database
    from tests.golive.test_item7_providers import Recorder
    rec = Recorder(ok({"id": "em_1"}))
    db = Database(tmp_path / "t.db")
    mail = email_mod.Email(to=ANN, subject="Hi", body="Body", kind="invoice",
                           attachments=(email_mod.Attachment("a.pdf", "application/pdf", b"%PDF-1.4"),))
    email_mod.ResendEmail(db, "k", "f@x.co", client=rec.client(), sleep=lambda s: None).send(mail)
    sent = json.loads(rec.requests[0].content)["attachments"]
    assert sent == [{"filename": "a.pdf", "content": "JVBERi0xLjQ=", "content_type": "application/pdf"}]
    assert email_mod.outbox(db)[0]["attachments"][0].data == b"%PDF-1.4"
