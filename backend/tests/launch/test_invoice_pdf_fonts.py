"""Run 5 addendum 0b: the invoice PDF embeds Noto Sans and Noto Sans Devanagari,
subset, each with a ToUnicode map. An invoice for ₹1,599 to a Hindi name and a
Latin name draws all three, and the text read back from the PDF is the text
given. Devanagari is shaped by HarfBuzz when uharfbuzz is installed; without it
the short-i matra is still drawn before its consonant."""
import re
import struct

import pytest

from app.billing import pdf, pdf_fonts
from tests.launch.test_paid_emails import _check_pdf, _objects, _stream_of, pdf_lines

HINDI, LATIN = "आशीष सिन्हा", "Ashish Sinha"


def _inv(**over) -> dict:
    inv = {"number": "VLT-2026-0042", "issued_at": "2026-10-28T00:00:00Z", "provider": "razorpay", "checkout_id": "order_1",
           "owner": "acct:1", "legal_name": HINDI, "gstin": "", "state_code": "29", "country": "IN",
           "description": f"Top-up for {LATIN}", "currency": "INR", "subtotal": 1355.08, "cgst": 121.96, "sgst": 121.96,
           "igst": 0.0, "total": 1599.0, "tax_kind": "intra", "test_mode": False}
    return inv | over


def _fonts(data: bytes) -> dict[str, bytes]:
    """BaseFont name (subset tag dropped) -> the embedded font program."""
    objs = _objects(data)
    out = {}
    for o in objs.values():
        if b"/FontFile2" in o:
            name = re.search(rb"/FontName /[A-Z]{6}\+([\w-]+)", o).group(1).decode()
            out[name] = _stream_of(objs[int(re.search(rb"/FontFile2 (\d+) 0 R", o).group(1))])
    return out


def test_rupees_a_hindi_name_and_a_latin_name_print_and_read_back_as_typed():
    data = pdf.invoice_pdf(_inv(), {"name": "Voltage", "gstin": "29ABCDE1234F1Z5", "state": "29"})
    _check_pdf(data, "Tax invoice", "Total", "₹1,599.00", "₹1,355.08", f"Top-up for {LATIN} (SAC", "Place of supply: Karnataka")
    assert HINDI in pdf_lines(data)                         # the whole line, exactly
    assert set(_fonts(data)) == {"NotoSans-Regular", "NotoSans-Bold", "NotoSansDevanagari-Regular"}
    assert data.count(b"/ToUnicode") == 3 and b"/Identity-H" in data
    assert b"Helvetica" not in data and b"Courier" not in data
    assert len(data) < 60_000                               # subset: the three fonts are ~1 MB whole


def test_a_latin_only_invoice_embeds_no_devanagari():
    data = pdf.invoice_pdf(_inv(legal_name="Ann (Studio) LLP"), {"name": "Voltage", "gstin": "", "state": "29"})
    assert set(_fonts(data)) == {"NotoSans-Regular", "NotoSans-Bold"}
    _check_pdf(data, "Ann (Studio) LLP", "₹1,599.00")


def test_the_subset_keeps_only_the_glyphs_drawn_and_is_a_valid_font():
    font = pdf_fonts.font(pdf_fonts.SANS)
    used = {font.cmap[ord(c)] for c in "₹1,599"}
    program = pdf_fonts.subset(font, used | {0})
    n = struct.unpack(">H", program[4:6])[0]
    tables = {}
    for i in range(n):
        tag, check, off, length = struct.unpack(">4sIII", program[12 + 16 * i: 28 + 16 * i])
        tables[tag.decode()] = program[off: off + length]
        if tag != b"head":
            assert pdf_fonts._checksum(program[off: off + length]) == check, tag
    assert pdf_fonts._checksum(program) == 0xB1B0AFBA       # the whole-file checksum the head records
    assert {"head", "hhea", "maxp", "hmtx", "loca", "glyf"} <= set(tables)
    loca = struct.unpack(f">{font.num_glyphs + 1}I", tables["loca"])
    drawn = {g for g in range(font.num_glyphs) if loca[g + 1] > loca[g]}
    assert used <= drawn and font.cmap[ord("Q")] not in drawn
    assert len(program) < len(font.data) // 10


def test_a_script_neither_font_has_draws_a_box_and_still_copies_out():
    name = "தமிழ் 中文 Zoë"
    data = pdf.invoice_pdf(_inv(legal_name=name), {"name": "Voltage", "gstin": "", "state": "29"})
    assert name in pdf_lines(data)
    [run] = pdf_fonts.runs("தமி")
    assert {g[0] for g in run.glyphs} == {0}                # .notdef, the empty box


def test_without_harfbuzz_the_short_i_matra_is_drawn_before_its_consonants():
    deva = pdf_fonts.font(pdf_fonts.DEVANAGARI)
    glyphs = deva._shape_plain("सिन्हा")
    assert [g[0] for g in glyphs[:2]] == [deva.cmap[0x093F], deva.cmap[ord("स")]]
    stacked = deva._shape_plain("स्त्रि")                   # moved before the whole cluster
    assert stacked[0][0] == deva.cmap[0x093F] and stacked[1][0] == deva.cmap[ord("स")]


def test_with_harfbuzz_devanagari_is_shaped():
    pytest.importorskip("uharfbuzz")
    deva = pdf_fonts.font(pdf_fonts.DEVANAGARI)
    [run] = pdf_fonts.runs("सिन्हा")
    gids = [g[0] for g in run.glyphs]
    assert gids[1] == deva.cmap[ord("स")] and gids[0] != deva.cmap[0x093F]   # a wider i-matra, drawn first
    assert len(gids) < len("सिन्हा") and deva.cmap[0x094D] not in gids       # न्ह as a conjunct, no visible virama
    assert "".join(g[1] for g in run.glyphs) == "सिन्हा"
