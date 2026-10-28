"""Run 4 item 4b: the tax invoice as a PDF, for the invoice email.

    invoice_pdf(inv, seller) -> bytes      one A4 page, text only, PDF 1.4

Written by hand (no PDF library). Run 5 addendum 0b: the text is set in
embedded, subset Noto Sans and Noto Sans Devanagari (billing.pdf_fonts), so
money prints with the rupee sign ("₹1,180.00") and a name prints as typed,
in Devanagari as well as Latin, Greek and Cyrillic. Every font carries a
ToUnicode map, so copying text out of the PDF gives the same words back.
The same rows as `billing.invoice_html`.
"""
from __future__ import annotations

from app.billing import gst, pdf_fonts

_W, _H = 595, 842                 # A4 in points
_LEFT, _RIGHT = 56, 539


def _money(amount: float, currency: str) -> str:
    return f"₹{float(amount):,.2f}" if currency == "INR" else f"${float(amount):,.2f}"   # as billing._money


class _Page:
    """Text lines from the top of the page down."""

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = _H - 64
        self.fonts: dict[str, pdf_fonts.Embed] = {}

    def _embed(self, font: pdf_fonts.Font) -> pdf_fonts.Embed:
        if font.name not in self.fonts:
            self.fonts[font.name] = pdf_fonts.Embed(font, f"F{len(self.fonts) + 1}")
        return self.fonts[font.name]

    def _draw(self, s: object, *, x: float, size: float, bold: bool) -> None:
        # One text object per string: each run ends where the next begins, whatever its font.
        ops = [f"BT {x:.2f} {self.y:g} Td"]
        for run in pdf_fonts.runs(" ".join(str(s).split()), bold=bold):
            e = self._embed(run.font)
            ops.append(f"/{e.resource} {size:g} Tf {e.show(run, size)}")
        self.ops.append(" ".join(ops + ["ET"]))

    def _width(self, s: str, size: float, bold: bool) -> float:
        return sum(r.width(size) for r in pdf_fonts.runs(s, bold=bold))

    def text(self, s: object, *, bold: bool = False, size: float = 10.5, x: float = _LEFT, gap: float = 15) -> None:
        self._draw(s, x=x, size=size, bold=bold)
        self.y -= gap

    def row(self, label: object, amount: str, *, bold: bool = False) -> None:
        # Amounts set flush right, measured from the font's own widths.
        size = 10.5
        self._draw(label, x=_LEFT, size=size, bold=bold)
        self._draw(amount, x=_RIGHT - self._width(amount, size, bold), size=size, bold=bold)
        self.y -= 6
        self.rule()
        self.y -= 14

    def rule(self) -> None:
        self.ops.append(f"0.87 0.87 0.84 RG 0.75 w {_LEFT} {self.y:g} m {_RIGHT} {self.y:g} l S")

    def space(self, points: float = 8) -> None:
        self.y -= points


def _document(page: _Page) -> bytes:
    content = "\n".join(page.ops).encode("latin-1")
    fonts, extra, n = [], [], 5
    for e in page.fonts.values():
        fonts.append(f"/{e.resource} {n} 0 R")
        parts = e.pdf_objects(n)
        extra += parts
        n += len(parts)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_W} {_H}] /Contents 4 0 R "
         f"/Resources << /Font << {' '.join(fonts)} >> >> >>").encode(),
        pdf_fonts._stream(content),
        *extra,
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
        p.text("Test mode. No money moved; this invoice is a sample of what a real one will look like.", bold=True, gap=26)
    p.text("Tax invoice", bold=True, size=22, gap=22)
    p.text(f"{inv['number']}, issued {str(inv['issued_at'])[:10]}, paid through {str(inv['provider']).title()} "
           f"({inv['checkout_id']})", size=9.5, gap=28)
    p.text("From", bold=True)
    p.text(seller.get("name") or "Voltage (seller details not set)")
    p.text(f"GSTIN {seller.get('gstin') or 'not set yet'}")
    p.text(gst.STATES.get(seller.get("state") or "", seller.get("state") or ""), gap=24)
    p.text("To", bold=True)
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
    return _document(p)
