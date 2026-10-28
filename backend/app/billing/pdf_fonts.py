"""Run 5 addendum 0b: embedded Unicode fonts for the invoice PDF.

    Text(faces).runs(s, bold=False) -> [Run]   s split by font, each run shaped
    Face.pdf_objects(...)                     the Type0 font, subset, for the PDF

Noto Sans (Latin, Greek, Cyrillic, the rupee sign) and Noto Sans Devanagari,
both SIL OFL 1.1 (fonts/OFL-*.txt; versions and sources in fonts/SOURCES.txt).
A character neither font has (Tamil, Bengali, CJK, Arabic, emoji) prints as
Noto Sans's empty box, and still copies out of the PDF as typed.

Shaping: with uharfbuzz installed (a dependency in pyproject.toml), HarfBuzz
shapes each run, so Devanagari gets its conjuncts, half forms and matras.
Without it (an environment that has not reinstalled), each character maps to
its own glyph and only the short-i matra is moved before its consonants:
Hindi stays readable, but a conjunct shows its virama ("न्ह" as न् + ह).

Subsetting is written here (no font library): the glyphs a PDF uses keep
their outlines and every other glyph is emptied, keeping glyph ids, so a CID
font with an identity map to glyph ids needs no renumbering.
"""
from __future__ import annotations

import functools
import hashlib
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

FONT_DIR = Path(__file__).with_name("fonts")
SANS, SANS_BOLD, DEVANAGARI = "NotoSans-Regular", "NotoSans-Bold", "NotoSansDevanagari-Regular"

try:  # HarfBuzz shaping, when installed
    import uharfbuzz as _hb  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on the environment
    _hb = None

SHAPED = _hb is not None

_VIRAMA, _I_MATRA, _ZWJ, _ZWNJ = 0x094D, 0x093F, 0x200D, 0x200C


def _devanagari(cp: int) -> bool:
    return 0x0900 <= cp <= 0x097F or 0xA8E0 <= cp <= 0xA8FF or 0x1CD0 <= cp <= 0x1CFF


def _consonant(cp: int) -> bool:
    return 0x0915 <= cp <= 0x0939 or 0x0958 <= cp <= 0x095F or 0x0978 <= cp <= 0x097F


class Font:
    """One TrueType file: the tables a CID font in a PDF needs."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.data = (FONT_DIR / f"{name}.ttf").read_bytes()
        n = struct.unpack(">H", self.data[4:6])[0]
        self.tables: dict[str, tuple[int, int]] = {}
        for i in range(n):
            tag, _sum, off, length = struct.unpack(">4sIII", self.data[12 + 16 * i: 28 + 16 * i])
            self.tables[tag.decode("latin-1")] = (off, length)
        head = self.table("head")
        self.upem = struct.unpack(">H", head[18:20])[0]
        self.bbox = struct.unpack(">hhhh", head[36:44])
        self.long_loca = struct.unpack(">h", head[50:52])[0] == 1
        self.num_glyphs = struct.unpack(">H", self.table("maxp")[4:6])[0]
        hhea = self.table("hhea")
        self.ascent, self.descent = struct.unpack(">hh", hhea[4:8])
        n_metrics = struct.unpack(">H", hhea[34:36])[0]
        hmtx = self.table("hmtx")
        adv = [struct.unpack(">H", hmtx[4 * i: 4 * i + 2])[0] for i in range(n_metrics)]
        self.advances = adv + [adv[-1]] * (self.num_glyphs - n_metrics)
        os2 = self.table("OS/2")
        self.cap_height = struct.unpack(">h", os2[88:90])[0] if len(os2) >= 90 else self.ascent
        self.cmap = self._read_cmap()
        self._hb_font = None

    def table(self, tag: str) -> bytes:
        off, length = self.tables[tag]
        return self.data[off: off + length]

    def _read_cmap(self) -> dict[int, int]:
        cmap = self.table("cmap")
        subtables = {}
        for i in range(struct.unpack(">H", cmap[2:4])[0]):
            pid, eid, off = struct.unpack(">HHI", cmap[4 + 8 * i: 12 + 8 * i])
            subtables[(pid, eid)] = off
        out: dict[int, int] = {}
        for key in ((3, 10), (0, 4), (3, 1), (0, 3)):
            if key not in subtables:
                continue
            off = subtables[key]
            fmt = struct.unpack(">H", cmap[off: off + 2])[0]
            if fmt == 12:
                for g in range(struct.unpack(">I", cmap[off + 12: off + 16])[0]):
                    start, end, gid = struct.unpack(">III", cmap[off + 16 + 12 * g: off + 28 + 12 * g])
                    for cp in range(start, end + 1):
                        out[cp] = gid + cp - start
                return out
            if fmt == 4:
                segs = struct.unpack(">H", cmap[off + 6: off + 8])[0] // 2
                ends = struct.unpack(f">{segs}H", cmap[off + 14: off + 14 + 2 * segs])
                base = off + 16 + 2 * segs
                starts = struct.unpack(f">{segs}H", cmap[base: base + 2 * segs])
                deltas = struct.unpack(f">{segs}h", cmap[base + 2 * segs: base + 4 * segs])
                ro_at = base + 4 * segs
                range_offs = struct.unpack(f">{segs}H", cmap[ro_at: ro_at + 2 * segs])
                for s in range(segs):
                    for cp in range(starts[s], ends[s] + 1):
                        if cp == 0xFFFF:
                            continue
                        if range_offs[s] == 0:
                            gid = (cp + deltas[s]) & 0xFFFF
                        else:
                            at = ro_at + 2 * s + range_offs[s] + 2 * (cp - starts[s])
                            gid = struct.unpack(">H", cmap[at: at + 2])[0]
                            gid = (gid + deltas[s]) & 0xFFFF if gid else 0
                        if gid:
                            out[cp] = gid
                return out
        return out

    def has(self, cp: int) -> bool:
        return cp in self.cmap

    # Shaping: (glyph id, cluster start, advance, dx, dy) per glyph, in font units.
    def shape(self, s: str) -> list[tuple[int, int, int, int, int]]:
        if _hb is not None:
            if self._hb_font is None:
                self._hb_font = _hb.Font(_hb.Face(_hb.Blob(self.data)))
            buf = _hb.Buffer()
            buf.add_codepoints([ord(c) for c in s])
            buf.guess_segment_properties()
            _hb.shape(self._hb_font, buf, {})
            return [(i.codepoint, i.cluster, p.x_advance, p.x_offset, p.y_offset)
                    for i, p in zip(buf.glyph_infos, buf.glyph_positions)]
        return self._shape_plain(s)

    def _shape_plain(self, s: str) -> list[tuple[int, int, int, int, int]]:
        """No HarfBuzz: one glyph per character, the short-i matra moved before its consonants."""
        order = list(range(len(s)))
        cluster = list(range(len(s)))
        i = 0
        while i < len(s):
            if ord(s[i]) == _I_MATRA and i > 0 and _consonant(ord(s[i - 1])):
                start = i - 1     # back over the consonant cluster: C (virama C)*
                while start >= 2 and ord(s[start - 1]) == _VIRAMA and _consonant(ord(s[start - 2])):
                    start -= 2
                order[start: i + 1] = [i] + order[start:i]
                for k in range(start, i + 1):
                    cluster[k] = start
            i += 1
        out = []
        for k in range(len(s)):
            ch = ord(s[order[k]])
            if ch in (_ZWJ, _ZWNJ):
                continue
            gid = self.cmap.get(ch, 0)
            out.append((gid, cluster[order[k]], self.advances[gid], 0, 0))
        return out


@functools.lru_cache(maxsize=None)
def font(name: str) -> Font:
    return Font(name)


@dataclass
class Run:
    """Shaped text in one font: glyphs (gid, text for ToUnicode, advance, dx, dy), font units."""
    font: Font
    glyphs: list[tuple[int, str, int, int, int]]

    def width(self, size: float) -> float:
        return sum(g[2] for g in self.glyphs) * size / self.font.upem


def runs(s: str, *, bold: bool = False) -> list[Run]:
    """`s` split into runs by font (Devanagari, else Noto Sans, else whichever has it), each shaped."""
    latin, deva = font(SANS_BOLD if bold else SANS), font(DEVANAGARI)
    pieces: list[tuple[Font, str]] = []
    for ch in s:
        cp = ord(ch)
        if _devanagari(cp):
            f = deva
        elif cp in (_ZWJ, _ZWNJ) or (ch.isspace() and deva.has(cp) and pieces and pieces[-1][0] is deva):
            f = pieces[-1][0] if pieces else latin
        elif latin.has(cp) or not deva.has(cp):
            f = latin
        else:
            f = deva
        if pieces and pieces[-1][0] is f:
            pieces[-1] = (f, pieces[-1][1] + ch)
        else:
            pieces.append((f, ch))
    out = []
    for f, text in pieces:
        shaped = f.shape(text)
        starts = sorted({g[1] for g in shaped} | {len(text)})
        nxt = {a: b for a, b in zip(starts, starts[1:])}
        count = {cl: sum(1 for g in shaped if g[1] == cl) for cl in nxt}
        used: dict[int, int] = {}
        glyphs = []
        for gid, cl, adv, dx, dy in shaped:
            # A cluster's text is dealt out over its glyphs in drawing order, the last glyph
            # taking the rest: "सि" is drawn matra first, and the matra copies as स, the
            # consonant as ि, so the copied text reads सि. More glyphs than characters: the
            # extra glyphs copy as nothing.
            j, chars = used.get(cl, 0), text[cl: nxt[cl]]
            used[cl] = j + 1
            piece = chars[j:] if j == count[cl] - 1 else chars[j: j + 1]
            glyphs.append((gid, piece, adv, dx, dy))
        out.append(Run(f, glyphs))
    return out


@dataclass
class Embed:
    """One font as used in one PDF: a code (CID) per distinct (glyph, text, width).

    The PDF width of a code is the shaped advance, less the glyph's offset, so the
    text position after it is where HarfBuzz puts the next glyph: no gaps in the
    TJ arrays that a reader copying text would take for spaces."""
    font: Font
    resource: str
    codes: dict[tuple[int, str, int], int] = field(default_factory=dict)

    def code(self, gid: int, text: str, width: int) -> int:
        return self.codes.setdefault((gid, text, width), len(self.codes) + 1)

    def show(self, run: Run, size: float) -> str:
        """Content-stream operators drawing `run` from the current text position."""
        scale = 1000 / self.font.upem
        ops: list[str] = []
        segment: list[list] = []   # [gid, text, width, move before] for one TJ at one rise
        rise = 0.0
        pen = drawn = 0
        # pen: where HarfBuzz puts the next glyph; drawn: where the PDF text position is.

        def flush() -> None:
            parts = []
            for gid, text, width, move in segment:
                if move:
                    parts.append(f"{-move * scale:.6g}")
                parts.append(f"<{self.code(gid, text, width):04X}>")
            if parts:
                ops.append(f"[{' '.join(parts)}] TJ")
            segment.clear()

        for gid, text, adv, dx, dy in run.glyphs:
            shift = (pen + dx) - drawn
            if shift and segment and segment[-1][2] + shift >= 0:
                segment[-1][2] += shift  # a mark's offset taken from the glyph before it
                shift = 0
            want_rise = dy * size / self.font.upem
            if want_rise != rise:
                flush()
                ops.append(f"{want_rise:.6g} Ts")
                rise = want_rise
            width = max(adv - dx, 0)
            segment.append([gid, text, width, shift])
            drawn = pen + dx + width
            pen += adv
        if pen != drawn:
            if segment and segment[-1][2] + pen - drawn >= 0:
                segment[-1][2] += pen - drawn   # end at the pen, where the next run starts
            else:
                ops.append(f"[{-(pen - drawn) * scale:.6g}] TJ")
        flush()
        if rise:
            ops.append("0 Ts")
        return " ".join(ops)

    def pdf_objects(self, first: int) -> list[bytes]:
        """The Type0 font and its parts as PDF objects numbered from `first` (the Type0 itself)."""
        f = self.font
        gids = sorted({0} | {g for g, _, _ in self.codes})
        tag = "".join(chr(65 + b % 26) for b in hashlib.sha256(repr(gids).encode()).digest()[:6])
        base = f"{tag}+{f.name}"
        scale = 1000 / f.upem
        by_code = sorted((c, g, t, w) for (g, t, w), c in self.codes.items())
        n_codes = len(by_code) + 1
        widths = " ".join(f"{c} [{w * scale:.6g}]" for c, _, _, w in by_code)
        cid_to_gid = bytearray(2 * n_codes)
        for c, g, _, _ in by_code:
            cid_to_gid[2 * c: 2 * c + 2] = struct.pack(">H", g)
        program = subset(f, set(gids))
        x0, y0, x1, y1 = (round(v * scale) for v in f.bbox)
        n = first
        return [
            (f"<< /Type /Font /Subtype /Type0 /BaseFont /{base} /Encoding /Identity-H "
             f"/DescendantFonts [{n + 1} 0 R] /ToUnicode {n + 2} 0 R >>").encode(),
            (f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{base} "
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
             f"/FontDescriptor {n + 3} 0 R /DW 0 /W [{widths}] /CIDToGIDMap {n + 4} 0 R >>").encode(),
            _stream(_to_unicode(by_code)),
            (f"<< /Type /FontDescriptor /FontName /{base} /Flags 32 /FontBBox [{x0} {y0} {x1} {y1}] "
             f"/ItalicAngle 0 /Ascent {f.ascent * scale:.0f} /Descent {f.descent * scale:.0f} "
             f"/CapHeight {f.cap_height * scale:.0f} /StemV 80 /FontFile2 {n + 5} 0 R >>").encode(),
            _stream(bytes(cid_to_gid)),
            _stream(program, f"/Length1 {len(program)}"),
        ]


def _stream(data: bytes, extra: str = "") -> bytes:
    packed = zlib.compress(data, 9)
    return (f"<< /Length {len(packed)} /Filter /FlateDecode {extra}>>\nstream\n".encode()
            + packed + b"\nendstream")


def _utf16_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _to_unicode(by_code: list[tuple[int, int, str, int]]) -> bytes:
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    for i in range(0, len(by_code), 100):
        chunk = by_code[i: i + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        lines += [f"<{c:04X}> <{_utf16_hex(t)}>" for c, _, t, _ in chunk]
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode()


# ---- subsetting -------------------------------------------------------------

_KEEP = ("head", "hhea", "maxp", "hmtx", "loca", "glyf", "cvt ", "fpgm", "prep", "OS/2")


def _glyph(f: Font, glyf: bytes, loca: list[int], gid: int) -> bytes:
    return glyf[loca[gid]: loca[gid + 1]]


def _components(data: bytes) -> list[int]:
    """The glyph ids a composite glyph draws."""
    if len(data) < 10 or struct.unpack(">h", data[:2])[0] >= 0:
        return []
    out, at = [], 10
    while True:
        flags, gid = struct.unpack(">HH", data[at: at + 4])
        out.append(gid)
        at += 4 + (4 if flags & 0x1 else 2)
        at += 2 if flags & 0x8 else 4 if flags & 0x40 else 8 if flags & 0x80 else 0
        if not flags & 0x20:
            return out


def subset(f: Font, gids: set[int]) -> bytes:
    """The font with every glyph outside `gids` (and their components) emptied, ids kept."""
    glyf = f.table("glyf")
    raw = f.table("loca")
    count = f.num_glyphs + 1
    loca = (list(struct.unpack(f">{count}I", raw[: 4 * count])) if f.long_loca
            else [2 * v for v in struct.unpack(f">{count}H", raw[: 2 * count])])
    keep, todo = set(), list(gids)
    while todo:
        g = todo.pop()
        if g in keep or g >= f.num_glyphs:
            continue
        keep.add(g)
        todo += _components(_glyph(f, glyf, loca, g))
    new_glyf, new_loca = bytearray(), []
    for g in range(f.num_glyphs):
        new_loca.append(len(new_glyf))
        if g in keep:
            data = _glyph(f, glyf, loca, g)
            new_glyf += data + b"\0" * (-len(data) % 4)
    new_loca.append(len(new_glyf))
    head = bytearray(f.table("head"))
    head[8:12] = b"\0\0\0\0"          # checkSumAdjustment, set below
    head[50:52] = struct.pack(">h", 1)  # long loca
    tables = {t: f.table(t) for t in _KEEP if t in f.tables}
    tables.update(head=bytes(head), glyf=bytes(new_glyf), loca=struct.pack(f">{len(new_loca)}I", *new_loca))
    return _sfnt(tables)


def _checksum(data: bytes) -> int:
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(data) // 4}I", data)) & 0xFFFFFFFF


def _sfnt(tables: dict[str, bytes]) -> bytes:
    tags = sorted(tables)
    n = len(tags)
    power = 1 << (n.bit_length() - 1)
    header = struct.pack(">IHHHH", 0x00010000, n, power * 16, power.bit_length() - 1, n * 16 - power * 16)
    offset = 12 + 16 * n
    directory, body = b"", b""
    for t in tags:
        data = tables[t]
        directory += struct.pack(">4sIII", t.encode("latin-1"), _checksum(data), offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    out = bytearray(header + directory + body)
    head_at = 12 + 16 * n + sum(len(tables[t]) + (-len(tables[t]) % 4) for t in tags[: tags.index("head")])
    out[head_at + 8: head_at + 12] = struct.pack(">I", (0xB1B0AFBA - _checksum(bytes(out))) & 0xFFFFFFFF)
    return bytes(out)
