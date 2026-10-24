"""Run 4 item 4b: the tax invoice as a PDF, for the invoice email.

    invoice_pdf(inv, seller) -> bytes      one A4 page, text only, PDF 1.4

Written by hand (no PDF library): the standard Helvetica and Courier fonts,
which every reader has, so nothing is embedded. Those fonts draw Latin-1
only, so money is written "INR 1,180.00" (no rupee sign) and any other
character in a name becomes "?"; the HTML invoice on the Billing page has
the name as typed. The same rows as `billing.invoice_html`.
"""
from __future__ import annotations

from app.billing import gst

_W, _H = 595, 842                 # A4 in points
_LEFT, _RIGHT = 56, 539


def _money(amount: float, currency: str) -> str:
    return f"{'INR' if currency == 'INR' else 'USD'} {float(amount):,.2f}"


def _pdf_text(s: object) -> str:
    """A PDF string literal's inside: Latin-1, with ( ) and backslash escaped."""
    raw = str(s).encode("cp1252", errors="replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", " ").replace("\n", " ")


class _Page:
    """Text lines from the top of the page down."""

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = _H - 64

    def text(self, s: object, *, font: str = "F1", size: float = 10.5, x: float = _LEFT, gap: float = 15) -> None:
        self.ops.append(f"BT /{font} {size:g} Tf {x:g} {self.y:g} Td ({_pdf_text(s)}) Tj ET")
        self.y -= gap

    def row(self, label: object, amount: str, *, bold: bool = False) -> None:
        # Amounts in Courier (every glyph 0.6 em wide), so they line up on the right.
        size = 10.5
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size:g} Tf {_LEFT} {self.y:g} Td ({_pdf_text(label)}) Tj ET")
        x = _RIGHT - len(amount) * 0.6 * size
        self.ops.append(f"BT /F3 {size:g} Tf {x:.2f} {self.y:g} Td ({_pdf_text(amount)}) Tj ET")
        self.y -= 6
        self.rule()
        self.y -= 14

    def rule(self) -> None:
        self.ops.append(f"0.87 0.87 0.84 RG 0.75 w {_LEFT} {self.y:g} m {_RIGHT} {self.y:g} l S")

    def space(self, points: float = 8) -> None:
        self.y -= points


def _document(content: bytes) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_W} {_H}] /Contents 4 0 R "
         "/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> >> >>").encode(),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def invoice_pdf(inv: dict, seller: dict) -> bytes:
    """A billing invoice row (billing.invoice) as a one-page PDF."""
    cur = inv["currency"]
    p = _Page()
    if inv.get("test_mode"):
        p.text("Test mode. No money moved; this invoice is a sample of what a real one will look like.", font="F2", gap=26)
    p.text("Tax invoice", font="F2", size=22, gap=22)
    p.text(f"{inv['number']}, issued {str(inv['issued_at'])[:10]}, paid through {str(inv['provider']).title()} "
           f"({inv['checkout_id']})", size=9.5, gap=28)
    p.text("From", font="F2")
    p.text(seller.get("name") or "Voltage (seller details not set)")
    p.text(f"GSTIN {seller.get('gstin') or 'not set yet'}")
    p.text(gst.STATES.get(seller.get("state") or "", seller.get("state") or ""), gap=24)
    p.text("To", font="F2")
    p.text(inv.get("legal_name") or inv["owner"])
    p.text(f"GSTIN {inv['gstin']}" if inv.get("gstin") else "No GSTIN")
    p.text(f"Place of supply: {gst.STATES.get(inv.get('state_code') or '', inv.get('country') or 'Outside India')}", gap=28)
    p.row("Description", "Amount", bold=True)
    p.row(f"{inv['description']} (SAC {gst.SAC})", _money(inv["subtotal"], cur))
    p.row("Taxable value", _money(inv["subtotal"], cur))
    if inv["tax_kind"] == "intra":
        p.row("CGST 9%", _money(inv["cgst"], cur))
        p.row("SGST 9%", _money(inv["sgst"], cur))
    elif inv["tax_kind"] == "inter":
        p.row("IGST 18%", _money(inv["igst"], cur))
    else:
        p.row("GST 0% (export of services)", _money(0, cur))
    p.row("Total", _money(inv["total"], cur), bold=True)
    return _document("\n".join(p.ops).encode("latin-1"))
