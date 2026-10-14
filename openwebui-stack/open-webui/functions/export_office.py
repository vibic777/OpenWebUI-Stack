"""
title: Export Documents and Images (DOCX / XLSX / PPTX / VSDX / PDF / MD / TXT / CSV / SVG / PNG / JPG)
author: openwebui-stack
version: 1.6.5
license: MIT
description: One Action with eleven document and image export buttons. Supports Office/PDF/text/table formats plus SVG source and embedded or same-origin Open WebUI PNG/JPG images. No admin-stack/code export actions.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import math
import re
import struct
import textwrap
import time
import urllib.parse
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape as _xml_escape

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# 1. Markdown -> blocks
# --------------------------------------------------------------------------------------

_THINK_RE = re.compile(r"<details[^>]*>.*?</details>|<think>.*?</think>", re.S | re.I)


def _content(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        bits = []
        for p in c:
            if isinstance(p, str):
                bits.append(p)
            elif isinstance(p, dict) and p.get("text"):
                bits.append(str(p["text"]))
        return "\n".join(bits)
    return ""


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", text)
    return re.sub(r"<br\s*/?>", "\n", text, flags=re.I).strip()


_INLINE_RE = re.compile(
    r"(\*\*(?P<b>.+?)\*\*|__(?P<b2>.+?)__|`(?P<c>[^`]+)`|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\)"
    r"|(?<![\w*])\*(?P<i>[^*\n]+?)\*(?![\w*])|(?<![\w_])_(?P<i2>[^_\n]+?)_(?![\w_]))"
)


def _runs(text: str) -> list[tuple[str, bool, bool, bool]]:
    """-> [(text, bold, italic, code)]"""
    out: list[tuple[str, bool, bool, bool]] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False, False, False))
        if m.group("b") or m.group("b2"):
            out.append((m.group("b") or m.group("b2"), True, False, False))
        elif m.group("c"):
            out.append((m.group("c"), False, False, True))
        elif m.group("lt"):
            out.append((f"{m.group('lt')} ({m.group('lu')})", False, False, False))
        else:
            out.append((m.group("i") or m.group("i2"), False, True, False))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False, False, False))
    return out or [("", False, False, False)]


def _plain(text: str) -> str:
    return "".join(r[0] for r in _runs(text))


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")


def parse_markdown(md: str) -> list[dict]:
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[dict] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append({"t": "p", "text": " ".join(s.strip() for s in para)})
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        fence = re.match(r"^(```|~~~)\s*([\w+-]*)", s)
        if fence:
            flush()
            mark, lang = fence.group(1), fence.group(2).lower()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith(mark):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append({"t": "code", "lang": lang, "text": "\n".join(buf)})
            continue
        if not s:
            flush()
            i += 1
            continue
        if "|" in s and i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]) and not _SEP_RE.match(ln):
            flush()
            rows = [_split_row(ln)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            blocks.append({"t": "table", "rows": rows})
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", s)
        if h:
            flush()
            blocks.append({"t": "h", "level": len(h.group(1)), "text": h.group(2)})
            i += 1
            continue
        if re.match(r"^([-*_])\1{2,}$", s.replace(" ", "")):
            flush()
            i += 1
            continue
        li = _LIST_RE.match(ln)
        if li:
            flush()
            indent = len(li.group(1).replace("\t", "    "))
            blocks.append(
                {
                    "t": "li",
                    "level": min(indent // 2, 3),
                    "ordered": li.group(2)[0].isdigit(),
                    "num": li.group(2).rstrip(".)"),
                    "text": li.group(3),
                }
            )
            i += 1
            continue
        if s.startswith(">"):
            flush()
            blocks.append({"t": "quote", "text": s.lstrip("> ").strip()})
            i += 1
            continue
        para.append(ln)
        i += 1
    flush()
    return blocks


def _title_of(blocks: list[dict], fallback: str = "Документ") -> str:
    for b in blocks:
        if b["t"] == "h":
            return _plain(b["text"])
    for b in blocks:
        if b["t"] == "p":
            return _plain(b["text"])[:60]
    return fallback


def _cell_value(text: str) -> Any:
    t = _plain(text).strip()
    if re.fullmatch(r"-?\d+", t) and not (len(t.lstrip("-")) > 1 and t.lstrip("-").startswith("0")) and len(t) < 16:
        return int(t)
    if re.fullmatch(r"-?\d+[.,]\d+", t):
        return float(t.replace(",", "."))
    return t


def _wlen(s: str) -> int:
    """display width: CJK counts double"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


# --------------------------------------------------------------------------------------
# 2. DOCX (python-docx)
# --------------------------------------------------------------------------------------


def _ea_font(style: Any, name: str = "Microsoft YaHei") -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


def build_docx(blocks: list[dict], title: str) -> bytes:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    for st in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Title", "List Bullet", "List Number"):
        try:
            _ea_font(doc.styles[st])
        except KeyError:
            pass
    doc.core_properties.title = title

    def add_runs(par: Any, text: str, size: Optional[int] = None) -> None:
        for t, b, i, c in _runs(text):
            r = par.add_run(t)
            r.bold = b or None
            r.italic = i or None
            if c:
                r.font.name = "Consolas"
            if size:
                r.font.size = Pt(size)

    for b in blocks:
        t = b["t"]
        if t == "h":
            doc.add_heading(_plain(b["text"]), level=min(b["level"], 4))
        elif t == "p":
            add_runs(doc.add_paragraph(), b["text"])
        elif t == "li":
            base = "List Number" if b["ordered"] else "List Bullet"
            style = base if b["level"] == 0 else f"{base} {min(b['level'] + 1, 3)}"
            try:
                par = doc.add_paragraph(style=style)
            except KeyError:
                par = doc.add_paragraph(style=base)
            add_runs(par, b["text"])
        elif t == "quote":
            try:
                par = doc.add_paragraph(style="Quote")
            except KeyError:
                par = doc.add_paragraph()
            add_runs(par, b["text"])
        elif t == "code":
            par = doc.add_paragraph()
            r = par.add_run(b["text"])
            r.font.name = "Consolas"
            r.font.size = Pt(9)
        elif t == "table":
            rows = b["rows"]
            tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
            tbl.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci, val in enumerate(row):
                    cell = tbl.cell(ri, ci)
                    par = cell.paragraphs[0]
                    if ri == 0:
                        r = par.add_run(_plain(val))
                        r.bold = True
                    else:
                        add_runs(par, val)
            doc.add_paragraph()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# 3. XLSX (openpyxl) - every markdown table becomes a sheet
# --------------------------------------------------------------------------------------


def build_xlsx(blocks: list[dict], title: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    tables = [b for b in blocks if b["t"] == "table"]
    if not tables:
        raise ValueError("В ответе нет таблиц (markdown | ... |). Попросите модель ответить таблицей.")
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    last_heading = ""
    idx = 0
    for b in blocks:
        if b["t"] == "h":
            last_heading = _plain(b["text"])
            continue
        if b["t"] != "table":
            continue
        idx += 1
        name = re.sub(r"[\[\]:*?/\\]", " ", last_heading or f"Таблица {idx}").strip()[:28] or f"Таблица {idx}"
        base, n = name, 2
        while name.lower() in used:
            name = f"{base[:25]} {n}"
            n += 1
        used.add(name.lower())
        ws = wb.create_sheet(name)
        for ri, row in enumerate(b["rows"], 1):
            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=ri, column=ci, value=_cell_value(val) if ri > 1 else _plain(val))
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if ri == 1:
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill("solid", fgColor="DDE7F5")
        for ci in range(1, len(b["rows"][0]) + 1):
            width = max(_wlen(_plain(r[ci - 1])) for r in b["rows"])
            ws.column_dimensions[get_column_letter(ci)].width = min(max(width + 2, 8), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        last_heading = ""
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# 4. PPTX (python-pptx) - 16:9, headings become slides
# --------------------------------------------------------------------------------------


def _pptx_run_fonts(run: Any, size: int, bold: bool = False, italic: bool = False, mono: bool = False) -> None:
    from pptx.oxml.ns import qn
    from pptx.util import Pt

    run.font.size = Pt(size)
    run.font.bold = bold or None
    run.font.italic = italic or None
    run.font.name = "Consolas" if mono else "Calibri"
    rpr = run._r.get_or_add_rPr()
    if rpr.find(qn("a:ea")) is None:
        from lxml import etree

        ea = etree.SubElement(rpr, qn("a:ea"))
        ea.set("typeface", "Microsoft YaHei")


def _pptx_bullet(par: Any, level: int, ordered: bool) -> None:
    from lxml import etree
    from pptx.oxml.ns import qn

    ppr = par._p.get_or_add_pPr()
    ppr.set("marL", str(320000 * (level + 1)))
    ppr.set("indent", "-280000")
    if ordered:
        bu = etree.SubElement(ppr, qn("a:buAutoNum"))
        bu.set("type", "arabicPeriod")
    else:
        bu = etree.SubElement(ppr, qn("a:buChar"))
        bu.set("char", "•")


def build_pptx(blocks: list[dict], title: str) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    L_TITLE, L_TITLE_ONLY = prs.slide_layouts[0], prs.slide_layouts[5]

    # --- group blocks into slides -------------------------------------------------
    slides: list[dict] = []
    cur: Optional[dict] = None
    doc_title = None
    first = True
    for b in blocks:
        if b["t"] == "h" and b["level"] <= 2:
            if first and b["level"] == 1 and doc_title is None:
                doc_title = _plain(b["text"])
                first = False
                continue
            cur = {"title": _plain(b["text"]), "items": []}
            slides.append(cur)
            first = False
            continue
        first = False
        if cur is None:
            cur = {"title": "Введение" if doc_title else title, "items": []}
            slides.append(cur)
        cur["items"].append(b)
    slides = [s for s in slides if s["items"]] or [{"title": title, "items": [{"t": "p", "text": "(пусто)"}]}]

    # --- title slide --------------------------------------------------------------
    s0 = prs.slides.add_slide(L_TITLE)
    s0.shapes.title.text = doc_title or title
    sub = s0.placeholders[1]
    sub.text = time.strftime("%d.%m.%Y")
    for shp, top, h, size in ((s0.shapes.title, 2.3, 1.6, 44), (sub, 4.1, 0.8, 20)):
        shp.left, shp.top, shp.width, shp.height = Inches(0.8), Inches(top), Inches(11.7), Inches(h)
        for par in shp.text_frame.paragraphs:
            for r in par.runs:
                _pptx_run_fonts(r, size, bold=(size > 30))

    def new_slide(text: str) -> Any:
        sl = prs.slides.add_slide(L_TITLE_ONLY)
        ti = sl.shapes.title
        ti.text = text
        ti.left, ti.top, ti.width, ti.height = Inches(0.6), Inches(0.35), Inches(12.1), Inches(1.0)
        for par in ti.text_frame.paragraphs:
            par.alignment = 1  # left
            for r in par.runs:
                _pptx_run_fonts(r, 30, bold=True)
        return sl

    def est_lines(item: dict) -> int:
        if item["t"] == "code":
            return item["text"].count("\n") + 1
        return max(1, math.ceil(_wlen(_plain(item.get("text", ""))) / 95))

    for sd in slides:
        text_items = [x for x in sd["items"] if x["t"] != "table"]
        tables = [x for x in sd["items"] if x["t"] == "table"]
        # text pages
        pages: list[list[dict]] = []
        page: list[dict] = []
        used = 0
        for it in text_items:
            n = est_lines(it) + (1 if it["t"] == "h" else 0)
            if page and used + n > 13:
                pages.append(page)
                page, used = [], 0
            page.append(it)
            used += n
        if page:
            pages.append(page)
        for pi, pg in enumerate(pages):
            sl = new_slide(sd["title"] + (f" ({pi + 1})" if len(pages) > 1 else ""))
            tb = sl.shapes.add_textbox(Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.6))
            tf = tb.text_frame
            tf.word_wrap = True
            total = sum(est_lines(x) for x in pg)
            size = 22 if total <= 7 else 20 if total <= 10 else 17
            firstp = True
            for it in pg:
                par = tf.paragraphs[0] if firstp else tf.add_paragraph()
                firstp = False
                par.space_after = Pt(6)
                if it["t"] == "code":
                    r = par.add_run()
                    r.text = it["text"]
                    _pptx_run_fonts(r, 13, mono=True)
                    continue
                if it["t"] == "h":
                    r = par.add_run()
                    r.text = _plain(it["text"])
                    _pptx_run_fonts(r, size + 2, bold=True)
                    continue
                if it["t"] == "li":
                    _pptx_bullet(par, it["level"], it["ordered"])
                for t, bld, itl, mono in _runs(it["text"]):
                    r = par.add_run()
                    r.text = t
                    _pptx_run_fonts(r, size - it.get("level", 0) * 2, bold=bld, italic=itl or it["t"] == "quote", mono=mono)
        # table pages
        for tb_ in tables:
            rows = tb_["rows"]
            head, body = rows[0], rows[1:] or [[""] * len(rows[0])]
            step = 9
            for ci in range(0, len(body), step):
                chunk = body[ci : ci + step]
                sl = new_slide(sd["title"] + (f" ({ci // step + 1})" if len(body) > step else ""))
                nrows, ncols = len(chunk) + 1, len(head)
                shape = sl.shapes.add_table(nrows, ncols, Inches(0.6), Inches(1.6), Inches(12.1), Inches(0.5) * nrows)
                tbl = shape.table
                fsize = 16 if ncols <= 3 else 13 if ncols <= 5 else 11
                for ri, row in enumerate([head] + chunk):
                    for cj, val in enumerate(row):
                        cell = tbl.cell(ri, cj)
                        tfc = cell.text_frame
                        tfc.word_wrap = True
                        par = tfc.paragraphs[0]
                        r = par.add_run()
                        r.text = _plain(val)
                        _pptx_run_fonts(r, fsize, bold=(ri == 0))
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# 5. PDF (stdlib writer + Noto font shipped with Open WebUI)
# --------------------------------------------------------------------------------------


def _font_path(override: str = "") -> Optional[Path]:
    dirs = [override] if override else []
    try:
        import open_webui  # type: ignore

        dirs.append(str(Path(open_webui.__file__).parent / "static" / "fonts"))
    except Exception:
        pass
    dirs += [
        "/app/backend/open_webui/static/fonts",
        "/app/backend/static/fonts",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation2",
    ]
    names = ("NotoSans-Regular.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    for directory in dirs:
        for name in names:
            candidate = Path(directory) / name
            if candidate.exists():
                return candidate
    return None


def _build_pdf_fallback(blocks: list[dict], title: str) -> bytes:
    """Create a dependency-free PDF with built-in Helvetica when no TTF is available.

    Standard PDF fonts do not contain Cyrillic glyphs, so unsupported characters are
    replaced with '?'. The export remains a valid, openable PDF instead of failing.
    """
    lines: list[tuple[str, int]] = [(title, 16)]
    for block in blocks:
        kind = block.get("t")
        if kind == "h":
            lines.append(("# " + _plain(block["text"]), max(12, 20 - block["level"] * 2)))
        elif kind == "p":
            lines.extend((_plain(line), 11) for line in textwrap.wrap(_plain(block["text"]), 92) or [""])
        elif kind == "li":
            mark = f"{block['num']}. " if block["ordered"] else "- "
            lines.extend(("  " * block["level"] + mark + line, 11) for line in textwrap.wrap(_plain(block["text"]), 86) or [""])
        elif kind == "quote":
            lines.extend(("> " + line, 11) for line in textwrap.wrap(_plain(block["text"]), 88) or [""])
        elif kind == "code":
            lines.append((f"[{block.get('lang', '')}]", 9))
            lines.extend((line, 9) for line in (block.get("text") or " ").splitlines())
        elif kind == "table":
            for row in block["rows"]:
                lines.extend((line, 10) for line in textwrap.wrap(" | ".join(_plain(v) for v in row), 88) or [""])
            lines.append(("", 10))

    def pdf_text(value: str) -> bytes:
        return b"(" + value.encode("latin-1", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

    objects: list[bytes] = []

    def obj(value: bytes) -> int:
        objects.append(value)
        return len(objects)

    font = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_lines = [b"q", b"BT"]
    y = 800
    for line, size in lines:
        content_lines += [f"/F1 {size} Tf 42 {y} Td ".encode("ascii") + pdf_text(line) + b" Tj", f"-0 -{max(15, size + 5)} Td".encode("ascii")]
        y -= max(15, size + 5)
        if y < 42:
            content_lines += [b"ET", b"Q"]
            break
    else:
        content_lines += [b"ET", b"Q"]
    stream = b"\n".join(content_lines)
    content = obj(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    page = obj(f"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode())
    pages = obj(f"<< /Type /Pages /Kids [{page} 0 R] /Count 1 >>".encode())
    catalog = obj(f"<< /Type /Catalog /Pages {pages} 0 R >>".encode())
    objects[page - 1] = objects[page - 1].replace(b"/Parent 4 0 R", f"/Parent {pages} 0 R".encode())
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    output += b"".join(f"{offsets[index]:010d} 00000 n \n".encode() for index in range(1, len(objects) + 1))
    output += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(output)


def build_pdf(blocks: list[dict], title: str, font_dir: str = "") -> bytes:
    font_path = _font_path(font_dir)
    if font_path is None:
        return _build_pdf_fallback(blocks, title)
    fd = font_path.parent
    landscape = any(b["t"] == "table" and len(b["rows"][0]) > 6 for b in blocks)
    font_data = font_path.read_bytes()
    width, height = ((842, 595) if landscape else (595, 842))
    margin = 42

    def ttf_tables(data: bytes) -> dict[str, tuple[int, int]]:
        tables = {}
        for i in range(struct.unpack_from(">H", data, 4)[0]):
            pos = 12 + i * 16
            tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, pos)
            tables[tag.decode("latin1")] = (offset, length)
        return tables

    def cmap(data: bytes) -> dict[int, int]:
        tables = ttf_tables(data)
        off, _ = tables["cmap"]
        count = struct.unpack_from(">H", data, off + 2)[0]
        candidates = []
        for i in range(count):
            platform, encoding, sub = struct.unpack_from(">HHI", data, off + 4 + i * 8)
            candidates.append((0 if platform == 3 and encoding in (1, 10) else 1 if platform == 0 else 2, off + sub))
        result: dict[int, int] = {}
        for _rank, sub in sorted(candidates):
            fmt = struct.unpack_from(">H", data, sub)[0]
            if fmt == 12:
                groups = struct.unpack_from(">I", data, sub + 12)[0]
                for i in range(groups):
                    start, end, gid = struct.unpack_from(">III", data, sub + 16 + i * 12)
                    for cp in range(start, end + 1):
                        result.setdefault(cp, gid + cp - start)
            elif fmt == 4:
                seg_count = struct.unpack_from(">H", data, sub + 6)[0] // 2
                ends = sub + 14
                starts = ends + seg_count * 2 + 2
                deltas = starts + seg_count * 2
                ranges = deltas + seg_count * 2
                for i in range(seg_count):
                    end = struct.unpack_from(">H", data, ends + i * 2)[0]
                    start = struct.unpack_from(">H", data, starts + i * 2)[0]
                    delta = struct.unpack_from(">h", data, deltas + i * 2)[0]
                    ro = struct.unpack_from(">H", data, ranges + i * 2)[0]
                    for cp in range(start, end + 1):
                        if cp == 0xFFFF:
                            continue
                        if ro == 0:
                            gid = (cp + delta) & 0xFFFF
                        else:
                            p = ranges + i * 2 + ro + (cp - start) * 2
                            gid = struct.unpack_from(">H", data, p)[0]
                            if gid:
                                gid = (gid + delta) & 0xFFFF
                        result.setdefault(cp, gid)
            if result:
                break
        return result

    def hex_text(text: str) -> str:
        return text.encode("utf-16-be", "surrogatepass").hex().upper()

    lines: list[tuple[str, int]] = []
    for block in blocks:
        kind = block["t"]
        if kind == "h":
            lines.append(("# " + _plain(block["text"]), max(14, 22 - block["level"] * 2)))
        elif kind == "p":
            lines.extend((_plain(line), 11) for line in textwrap.wrap(_plain(block["text"]), 92) or [""])
        elif kind == "li":
            mark = f"{block['num']}. " if block["ordered"] else "• "
            lines.extend(("  " * block["level"] + mark + line, 11) for line in textwrap.wrap(_plain(block["text"]), 86) or [""])
        elif kind == "quote":
            lines.extend(("> " + line, 11) for line in textwrap.wrap(_plain(block["text"]), 88) or [""])
        elif kind == "code":
            lines.append((f"[{block.get('lang', '')}]", 9))
            lines.extend((line, 9) for line in (block["text"] or " ").splitlines())
        elif kind == "table":
            for row in block["rows"]:
                lines.extend((line, 10) for line in textwrap.wrap(" | ".join(_plain(v) for v in row), 88) or [""])
            lines.append(("", 10))

    used = "".join(line for line, _size in lines) + title
    glyphs = cmap(font_data)
    max_cp = max([ord(ch) for ch in used if ord(ch) <= 0xFFFF] + [0])
    cid_map = bytearray((max_cp + 1) * 2)
    for cp in range(max_cp + 1):
        struct.pack_into(">H", cid_map, cp * 2, glyphs.get(cp, 0))
    to_unicode = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap", "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def", "/CMapName /NotoUnicode def", "/CMapType 2 def", "1 begincodespacerange", "<0000> <%04X>" % max_cp, "endcodespacerange"]
    chars = sorted({ord(ch) for ch in used if ord(ch) <= 0xFFFF})
    for start in range(0, len(chars), 100):
        chunk = chars[start : start + 100]
        to_unicode.append(f"{len(chunk)} beginbfchar")
        to_unicode.extend(f"<{cp:04X}> <{cp:04X}>" for cp in chunk)
        to_unicode.append("endbfchar")
    to_unicode += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    unicode_data = "\n".join(to_unicode).encode("ascii")

    objects: list[bytes] = []
    def obj(value: bytes) -> int:
        objects.append(value)
        return len(objects)
    font_file = obj(b"<< /Length %d /Length1 %d /Filter /FlateDecode >>\nstream\n" % (len(zlib.compress(font_data)), len(font_data)) + zlib.compress(font_data) + b"\nendstream")
    to_unicode_obj = obj(b"<< /Length %d >>\nstream\n" % len(unicode_data) + unicode_data + b"\nendstream")
    descriptor = obj(f"<< /Type /FontDescriptor /FontName /NotoSans /Flags 4 /FontBBox [0 -300 2000 1100] /ItalicAngle 0 /Ascent 1000 /Descent -300 /CapHeight 700 /StemV 80 /FontFile2 {font_file} 0 R >>".encode())
    cid_font = obj(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /NotoSans /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor {descriptor} 0 R /DW 600 /CIDToGIDMap ".encode() + str(obj(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(zlib.compress(cid_map)) + zlib.compress(cid_map) + b"\nendstream")).encode() + b" 0 R >>")
    type0 = obj(f"<< /Type /Font /Subtype /Type0 /BaseFont /NotoSans /Encoding /Identity-H /DescendantFonts [{cid_font} 0 R] /ToUnicode {to_unicode_obj} 0 R >>".encode())

    content_pages: list[int] = []
    page_lines = max(1, int((height - margin * 2) / 16))
    for page_start in range(0, len(lines) or 1, page_lines):
        content = ["q", "BT"]
        y = height - margin
        for line, size in lines[page_start : page_start + page_lines]:
            content += [f"/F1 {size} Tf 1 0 0 1 {margin} {y:.1f} Tm <{hex_text(line)}> Tj"]
            y -= 16 if size <= 11 else 24
        content += ["ET", "Q"]
        raw = "\n".join(content).encode("ascii")
        stream = zlib.compress(raw)
        content_obj = obj(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_pages.append(content_obj)
    pages_obj = obj(b"")
    page_objs = []
    for content_obj in content_pages:
        page_objs.append(obj(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 {type0} 0 R >> >> /Contents {content_obj} 0 R >>".encode()))
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{ ' '.join(f'{p} 0 R' for p in page_objs) }] /Count {len(page_objs)} >>".encode()
    catalog = obj(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode())
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(out)); out += f"{i} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(out); out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offsets[i]:010d} 00000 n \n".encode() for i in range(1, len(objects)+1))
    out += f"trailer\n<< /Size {len(objects)+1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def build_pdf_html(blocks: list[dict], title: str) -> str:
    """Build a browser-printable HTML representation when no usable TTF exists."""
    from html import escape

    body: list[str] = []
    for block in blocks:
        kind = block.get("t")
        if kind == "h":
            level = min(max(int(block.get("level", 1)), 1), 6)
            body.append(f"<h{level}>{escape(_plain(block['text']))}</h{level}>")
        elif kind == "p":
            body.append(f"<p>{escape(_plain(block['text']))}</p>")
        elif kind == "li":
            tag = "ol" if block.get("ordered") else "ul"
            body.append(f"<{tag}><li>{escape(_plain(block['text']))}</li></{tag}>")
        elif kind == "quote":
            body.append(f"<blockquote>{escape(_plain(block['text']))}</blockquote>")
        elif kind == "code":
            body.append(f"<pre>{escape(block.get('text', ''))}</pre>")
        elif kind == "table":
            rows = block.get("rows", [])
            if rows:
                head = "".join(f"<th>{escape(_plain(str(cell)))}</th>" for cell in rows[0])
                rest = "".join("<tr>" + "".join(f"<td>{escape(_plain(str(cell)))}</td>" for cell in row) + "</tr>" for row in rows[1:])
                body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rest}</tbody></table>")
    wide = any(b.get("t") == "table" and b.get("rows") and len(b["rows"][0]) > 6 for b in blocks)
    orientation = "landscape" if wide else "portrait"
    css = (
        f"@page{{size:A4 {orientation};margin:15mm}}body{{font-family:'Noto Sans','DejaVu Sans',Arial,sans-serif;font-size:11pt;line-height:1.45;color:#111}}"
        "h1{font-size:20pt}h2{font-size:16pt}h3{font-size:14pt}h4,h5,h6{font-size:12pt}"
        "table{border-collapse:collapse;width:100%;margin:8px 0;font-size:10pt}th,td{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}th{background:#dde7f5}"
        "pre{background:#f2f2f2;padding:8px;white-space:pre-wrap;font-family:Consolas,'DejaVu Sans Mono',monospace;font-size:9pt}"
        "blockquote{margin:6px 0 6px 12px;padding-left:8px;border-left:3px solid #ccc;font-style:italic}"
    )
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


def _js_print_html(document: str) -> str:
    # Передаём Unicode через srcdoc, а не через atob/document.write:
    # atob возвращает Latin-1-строку и превращает UTF-8 кириллицу в кракозябры.
    return f"""
(function() {{
  const f = document.createElement("iframe");
  f.style.position = "fixed"; f.style.right = "0"; f.style.bottom = "0";
  f.style.width = "0"; f.style.height = "0"; f.style.border = "0";
  document.body.appendChild(f);
  f.onload = () => {{ setTimeout(() => {{
    f.contentWindow.focus(); f.contentWindow.print();
    setTimeout(() => f.remove(), 60000);
  }}, 300); }};
  f.srcdoc = {json.dumps(document, ensure_ascii=True)};
}})();
"""


# --------------------------------------------------------------------------------------
# 6. VSDX (Visio) - hand-written OPC package (stdlib zipfile)
# --------------------------------------------------------------------------------------

_MM_NODE = re.compile(
    r"^\s*(?P<id>[\wЀ-ӿ一-鿿.-]+)\s*"
    r"(?:(?P<shape>\(\(.*?\)\)|\[\[.*?\]\]|\[.*?\]|\(.*?\)|\{.*?\}|>.*?\]))?\s*"
)
_MM_EDGE = re.compile(r"^\s*(?:-\.->|-->|==>|---|-\.-|--[xo]|<-->)\s*(?:\|(?P<l1>[^|]*)\|)?\s*")
_MM_EDGE_TXT = re.compile(r"^\s*--\s+(?P<l2>[^->|]+?)\s+-->\s*")


def _mm_label(shape: Optional[str], fallback: str) -> tuple[str, str]:
    if not shape:
        return fallback, "rect"
    kind = "rect"
    if shape.startswith("{"):
        kind = "diamond"
    elif shape.startswith("(") or shape.startswith("[["):
        kind = "round"
    inner = shape.strip("[](){}>").strip().strip('"').strip("'")
    return (inner or fallback), kind


def parse_mermaid(src: str) -> Optional[dict]:
    lines = [ln.strip() for ln in src.replace("\r", "").split("\n") if ln.strip() and not ln.strip().startswith("%%")]
    if not lines or not re.match(r"^(flowchart|graph)\b", lines[0], re.I):
        return None
    horizontal = bool(re.match(r"^(flowchart|graph)\s+(LR|RL)\b", lines[0], re.I))
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str, str]] = []
    for ln in lines[1:]:
        if re.match(r"^(subgraph|end|classDef|class|style|linkStyle|click|direction)\b", ln, re.I):
            continue
        for stmt in ln.split(";"):
            rest = stmt
            prev: Optional[str] = None
            pending_label = ""
            while rest.strip():
                m = _MM_NODE.match(rest)
                if not m:
                    break
                nid = m.group("id")
                label, kind = _mm_label(m.group("shape"), nid)
                if nid not in nodes or m.group("shape"):
                    nodes[nid] = {"label": label, "kind": kind}
                if prev is not None:
                    edges.append((prev, nid, pending_label))
                prev, pending_label = nid, ""
                rest = rest[m.end():]
                e = _MM_EDGE_TXT.match(rest) or _MM_EDGE.match(rest)
                if not e:
                    break
                pending_label = ((e.groupdict().get("l1") or e.groupdict().get("l2")) or "").strip()
                rest = rest[e.end():]
    if not nodes:
        return None
    return {"nodes": nodes, "edges": edges, "horizontal": horizontal}


def _outline_graph(blocks: list[dict]) -> dict:
    """no mermaid: headings/lists become a tree; otherwise a simple top-down chain"""
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str, str]] = []
    stack: list[tuple[int, str]] = []
    n = 0
    has_heading = any(b["t"] == "h" for b in blocks)

    def add(label: str, kind: str = "rect") -> str:
        nonlocal n
        n += 1
        nid = f"n{n}"
        nodes[nid] = {"label": label[:80], "kind": kind}
        return nid

    if has_heading:
        for b in blocks:
            if n >= 80:
                break
            if b["t"] == "h":
                nid = add(_plain(b["text"]))
                while stack and stack[-1][0] >= b["level"]:
                    stack.pop()
                if stack:
                    edges.append((stack[-1][1], nid, ""))
                stack.append((b["level"], nid))
            elif b["t"] == "li" and stack:
                nid = add(_plain(b["text"]), "round")
                edges.append((stack[-1][1], nid, ""))
    else:
        prev = None
        for b in blocks:
            if b["t"] in ("li", "p") and n < 40:
                nid = add(_plain(b["text"]), "round" if b["t"] == "li" else "rect")
                if prev:
                    edges.append((prev, nid, ""))
                prev = nid
    return {"nodes": nodes, "edges": edges, "horizontal": False}


def _layout(g: dict) -> dict[str, tuple[float, float, float, float]]:
    """-> {id: (cx, cy, w, h)} in inches, origin bottom-left (Visio)"""
    nodes, edges = g["nodes"], g["edges"]
    layer: dict[str, int] = {k: 0 for k in nodes}
    adj: dict[str, list[str]] = {k: [] for k in nodes}
    for a, b, _ in edges:
        if a in adj and b in nodes:
            adj[a].append(b)
    state: dict[str, int] = {}
    order: list[str] = []

    def dfs(u: str) -> None:
        state[u] = 1
        for v in adj[u]:
            if state.get(v, 0) == 0:
                dfs(v)
        state[u] = 2
        order.append(u)

    import sys

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 3000))
    for k in nodes:
        if state.get(k, 0) == 0:
            dfs(k)
    pos = {k: i for i, k in enumerate(reversed(order))}  # topological-ish order
    for u in reversed(order):
        for v in adj[u]:
            if pos[v] > pos[u]:  # ignore back edges (cycles)
                layer[v] = max(layer[v], layer[u] + 1)
    by_layer: dict[int, list[str]] = {}
    for k in nodes:  # keep insertion order inside a layer
        by_layer.setdefault(layer[k], []).append(k)
    size: dict[str, tuple[float, float]] = {}
    for k, nd in nodes.items():
        w = min(3.4, max(1.7, 0.11 * _wlen(nd["label"]) / 2 + 0.9))
        h = 0.8 if _wlen(nd["label"]) < 28 else 1.1
        size[k] = (w, h * (1.25 if nd["kind"] == "diamond" else 1.0))
    gap_x, gap_y = 0.6, 0.9
    horizontal = g["horizontal"]
    res: dict[str, tuple[float, float, float, float]] = {}
    maxw = 0.0
    spans = {}
    for li, ids in by_layer.items():
        spans[li] = sum((size[i][1] if horizontal else size[i][0]) for i in ids) + gap_x * (len(ids) - 1)
        maxw = max(maxw, spans[li])
    layer_dim = {li: max((size[i][0] if horizontal else size[i][1]) for i in ids) for li, ids in by_layer.items()}
    nl = len(by_layer)
    total_depth = sum(layer_dim.values()) + gap_y * (nl - 1)
    margin = 0.8
    depth_cursor = margin
    for li in sorted(by_layer):
        ids = by_layer[li]
        cursor = margin + (maxw - spans[li]) / 2
        for i in ids:
            w, h = size[i]
            along = (h if horizontal else w)
            c_along = cursor + along / 2
            c_depth = depth_cursor + layer_dim[li] / 2
            if horizontal:
                res[i] = (c_depth, c_along, w, h)
            else:
                res[i] = (c_along, c_depth, w, h)
            cursor += along + gap_x
        depth_cursor += layer_dim[li] + gap_y
    # convert to Visio coordinates (y up); for TD the first layer must be on top
    W = (total_depth if horizontal else maxw) + 2 * margin
    H = (maxw if horizontal else total_depth) + 2 * margin
    out = {}
    for i, (cx, cy, w, h) in res.items():
        out[i] = (cx, H - cy, w, h)
    out["__page__"] = (W, H, 0, 0)  # type: ignore[assignment]
    return out


def build_vsdx(blocks: list[dict], title: str) -> bytes:
    graph = None
    mermaid_blocks = [b for b in blocks if b["t"] == "code" and b["lang"] in ("mermaid", "mmd")]
    for b in blocks:
        if b["t"] == "code" and b["lang"] in ("mermaid", "mmd", ""):
            graph = parse_mermaid(b["text"])
            if graph:
                break
    if graph is None:
        if mermaid_blocks:
            raise ValueError("Блок Mermaid найден, но формат не распознан. Используйте только flowchart TD/LR с простыми узлами и связями -->.")
        graph = _outline_graph(blocks)
    if not graph["nodes"]:
        raise ValueError("Нечего рисовать: нужен блок ```mermaid flowchart``` или заголовки/списки в ответе.")
    lay = _layout(graph)
    page_w, page_h, _, _ = lay.pop("__page__")  # type: ignore[misc]
    ids: dict[str, int] = {}
    shapes: list[str] = []
    nid = 0
    fills = {"rect": "#DAE8FC", "round": "#D5E8D4", "diamond": "#FFF2CC"}
    lines = {"rect": "#6C8EBF", "round": "#82B366", "diamond": "#D6B656"}

    def cell(n: str, v: Any, f: str = "") -> str:
        return f'<Cell N="{n}" V="{v}"' + (f' F="{f}"' if f else "") + "/>"

    def xf(cx: float, cy: float, w: float, h: float) -> str:
        return (
            cell("PinX", f"{cx:.4f}") + cell("PinY", f"{cy:.4f}") + cell("Width", f"{w:.4f}") + cell("Height", f"{h:.4f}")
            + cell("LocPinX", f"{w / 2:.4f}", "Width*0.5") + cell("LocPinY", f"{h / 2:.4f}", "Height*0.5") + cell("Angle", 0)
        )

    for key, nd in graph["nodes"].items():
        nid += 1
        ids[key] = nid
        cx, cy, w, h = lay[key]
        kind = nd["kind"]
        if kind == "diamond":
            geo = (
                f'<Row T="MoveTo" IX="1">{cell("X", f"{w / 2:.4f}", "Width*0.5")}{cell("Y", 0)}</Row>'
                f'<Row T="LineTo" IX="2">{cell("X", f"{w:.4f}", "Width")}{cell("Y", f"{h / 2:.4f}", "Height*0.5")}</Row>'
                f'<Row T="LineTo" IX="3">{cell("X", f"{w / 2:.4f}", "Width*0.5")}{cell("Y", f"{h:.4f}", "Height")}</Row>'
                f'<Row T="LineTo" IX="4">{cell("X", 0)}{cell("Y", f"{h / 2:.4f}", "Height*0.5")}</Row>'
                f'<Row T="LineTo" IX="5">{cell("X", f"{w / 2:.4f}", "Width*0.5")}{cell("Y", 0)}</Row>'
            )
        else:
            geo = (
                f'<Row T="MoveTo" IX="1">{cell("X", 0)}{cell("Y", 0)}</Row>'
                f'<Row T="LineTo" IX="2">{cell("X", f"{w:.4f}", "Width")}{cell("Y", 0)}</Row>'
                f'<Row T="LineTo" IX="3">{cell("X", f"{w:.4f}", "Width")}{cell("Y", f"{h:.4f}", "Height")}</Row>'
                f'<Row T="LineTo" IX="4">{cell("X", 0)}{cell("Y", f"{h:.4f}", "Height")}</Row>'
                f'<Row T="LineTo" IX="5">{cell("X", 0)}{cell("Y", 0)}</Row>'
            )
        shapes.append(
            f'<Shape ID="{nid}" Type="Shape" NameU="Sheet.{nid}" Name="{_xml_escape(nd["label"][:30], {chr(34): "&quot;"})}">'
            + xf(cx, cy, w, h)
            + cell("FillForegnd", fills[kind]) + cell("LineColor", lines[kind]) + cell("LineWeight", "0.02")
            + cell("VerticalAlign", 1) + cell("LeftMargin", "0.05") + cell("RightMargin", "0.05")
            + f'<Section N="Geometry" IX="0">{cell("NoFill", 0)}{cell("NoLine", 0)}{geo}</Section>'
            + f"<Text>{_xml_escape(nd['label'])}</Text></Shape>"
        )
    # connectors: plain lines with an arrow head (not glued)
    for a, b, label in graph["edges"]:
        if a not in lay or b not in lay:
            continue
        ax, ay, aw, ah = lay[a]
        bx, by, bw, bh = lay[b]
        # start/end on the facing borders
        if graph["horizontal"]:
            sx, sy = ax + (aw / 2 if bx >= ax else -aw / 2), ay
            ex, ey = bx - (bw / 2 if bx >= ax else -bw / 2), by
        else:
            sx, sy = ax, ay + (-ah / 2 if by <= ay else ah / 2)
            ex, ey = bx, by + (bh / 2 if by <= ay else -bh / 2)
        nid += 1
        minx, miny = min(sx, ex), min(sy, ey)
        w, h = max(abs(ex - sx), 0.0001), max(abs(ey - sy), 0.0001)
        geo = (
            f'<Row T="MoveTo" IX="1">{cell("X", f"{sx - minx:.4f}")}{cell("Y", f"{sy - miny:.4f}")}</Row>'
            f'<Row T="LineTo" IX="2">{cell("X", f"{ex - minx:.4f}")}{cell("Y", f"{ey - miny:.4f}")}</Row>'
        )
        shapes.append(
            f'<Shape ID="{nid}" Type="Shape" NameU="Connector.{nid}" Name="Connector">'
            + cell("PinX", f"{minx:.4f}") + cell("PinY", f"{miny:.4f}") + cell("Width", f"{w:.4f}") + cell("Height", f"{h:.4f}")
            + cell("LocPinX", 0) + cell("LocPinY", 0) + cell("Angle", 0)
            + cell("LineColor", "#444444") + cell("LineWeight", "0.015") + cell("EndArrow", 13) + cell("EndArrowSize", 2)
            + f'<Section N="Geometry" IX="0">{cell("NoFill", 1)}{cell("NoLine", 0)}{geo}</Section></Shape>'
        )
        if label:
            nid += 1
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            lw = min(2.4, 0.11 * _wlen(label) / 2 + 0.3)
            shapes.append(
                f'<Shape ID="{nid}" Type="Shape" NameU="Label.{nid}" Name="Label">'
                + xf(mx, my, lw, 0.3)
                + cell("FillForegnd", "#FFFFFF") + cell("LineColor", "#FFFFFF") + cell("LinePattern", 0)
                + f'<Section N="Geometry" IX="0">{cell("NoFill", 0)}{cell("NoLine", 1)}'
                f'<Row T="MoveTo" IX="1">{cell("X", 0)}{cell("Y", 0)}</Row>'
                f'<Row T="LineTo" IX="2">{cell("X", f"{lw:.4f}", "Width")}{cell("Y", 0)}</Row>'
                f'<Row T="LineTo" IX="3">{cell("X", f"{lw:.4f}", "Width")}{cell("Y", "0.3", "Height")}</Row>'
                f'<Row T="LineTo" IX="4">{cell("X", 0)}{cell("Y", "0.3", "Height")}</Row>'
                f'<Row T="LineTo" IX="5">{cell("X", 0)}{cell("Y", 0)}</Row></Section>'
                + f"<Text>{_xml_escape(label)}</Text></Shape>"
            )
    X = '<?xml version="1.0" encoding="utf-8"?>'
    ns = "http://schemas.microsoft.com/office/visio/2012/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    parts = {
        "[Content_Types].xml": X + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
        '<Override PartName="/visio/windows.xml" ContentType="application/vnd.ms-visio.windows+xml"/>'
        '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
        '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
        '<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/></Types>',
        "_rels/.rels": X + f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
        'Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/></Relationships>',
        "docProps/app.xml": X + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Open WebUI</Application><AppVersion>1.0</AppVersion></Properties>',
        "docProps/core.xml": X + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + _xml_escape(title) + '</dc:title><dc:creator>Open WebUI</dc:creator></cp:coreProperties>',
        "docProps/custom.xml": X + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>',
        "visio/document.xml": X + f'<VisioDocument xmlns="{ns}" xmlns:r="{rns}" xml:space="preserve"><DocumentSettings TopPage="0" DefaultTextStyle="0" DefaultLineStyle="0" DefaultFillStyle="0" DefaultGuideStyle="0"><GlueSettings>9</GlueSettings><SnapSettings>65879</SnapSettings><DynamicGridEnabled>1</DynamicGridEnabled><ProtectStyles>0</ProtectStyles></DocumentSettings><Colors/><FaceNames/><StyleSheets/></VisioDocument>',
        "visio/_rels/document.xml.rels": X + f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
        'Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.microsoft.com/visio/2010/relationships/windows" Target="windows.xml"/></Relationships>',
        "visio/windows.xml": X + f'<Windows xmlns="{ns}"><Window ID="0" WindowType="Drawing" ViewCenterX="{page_w / 2:.4f}" ViewCenterY="{page_h / 2:.4f}" ViewScale="1" ShowGrid="1" ShowGuides="1" ShowPageBreaks="1"/></Windows>',
        "visio/pages/pages.xml": X + f'<Pages xmlns="{ns}" xmlns:r="{rns}" xml:space="preserve">'
        f'<Page ID="0" NameU="Page-1" Name="{_xml_escape(title[:30], {chr(34): "&quot;"})}" ViewScale="1" ViewCenterX="{page_w / 2:.4f}" ViewCenterY="{page_h / 2:.4f}"><PageSheet LineStyle="0" FillStyle="0" TextStyle="0">'
        f'<Cell N="PageWidth" V="{page_w:.4f}" U="IN"/><Cell N="PageHeight" V="{page_h:.4f}" U="IN"/>'
        '<Cell N="PageScale" V="1" U="IN_F"/><Cell N="DrawingScale" V="1" U="IN_F"/><Section N="Layer"/></PageSheet>'
        '<Rel r:id="rId1"/></Page></Pages>',
        "visio/pages/_rels/pages.xml.rels": X + f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
        'Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/></Relationships>',
        "visio/pages/_rels/page1.xml.rels": X + f'<Relationships xmlns="{pkg}"/>',
        "visio/pages/page1.xml": X + f'<PageContents xmlns="{ns}" xmlns:r="{rns}" xml:space="preserve"><Shapes>'
        + "".join(shapes) + "</Shapes></PageContents>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def build_txt(blocks: list[dict]) -> bytes:
    """Render parsed Markdown blocks as readable plain text, without Markdown markers."""
    lines: list[str] = []
    in_list = False
    for block in blocks:
        kind = block.get("t")
        if kind == "li":
            if not in_list and lines and lines[-1] != "":
                lines.append("")
            prefix = " " * (int(block.get("level", 0)) * 2)
            marker = f"{block.get('num', '1')}. " if block.get("ordered") else "- "
            lines.append(prefix + marker + _plain(block.get("text", "")))
            in_list = True
            continue
        if lines and lines[-1] != "":
            lines.append("")
        if kind == "h" or kind == "p":
            lines.append(_plain(block.get("text", "")))
        elif kind == "quote":
            lines.append(_plain(block.get("text", "")))
        elif kind == "code":
            lines.extend(block.get("text", "").splitlines())
        elif kind == "table":
            lines.extend("\t".join(_plain(cell) for cell in row) for row in block.get("rows", []))
        in_list = False
    text = "\n".join(lines).strip()
    return ((text + "\n") if text else "").encode("utf-8")


def build_csv(blocks: list[dict]) -> bytes:
    """Export Markdown table blocks as RFC-style UTF-8 CSV with a header row."""
    tables = [b for b in blocks if b.get("t") == "table" and b.get("rows")]
    if not tables:
        raise ValueError("В ответе не найдена markdown-таблица для экспорта CSV.")
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, dialect="excel", lineterminator="\r\n")
    for index, table in enumerate(tables):
        if index:
            writer.writerow([])
        writer.writerows([[_plain(str(cell)) for cell in row] for row in table["rows"]])
    return buf.getvalue().encode("utf-8")


# --------------------------------------------------------------------------------------
# 7. Open WebUI Action
# --------------------------------------------------------------------------------------

FORMATS = {
    "docx": ("DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "#2B579A", "W"),
    "xlsx": ("XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "#217346", "X"),
    "pptx": ("PPTX", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "#D24726", "P"),
    "vsdx": ("VSDX", "application/vnd.ms-visio.drawing", "#3955A3", "V"),
    "pdf": ("PDF", "application/pdf", "#C8102E", "F"),
    "md": ("MD", "text/markdown", "#4B5563", "M"),
    "txt": ("TXT", "text/plain", "#5C5C5C", "T"),
    "csv": ("CSV", "text/csv", "#217346", "C"),
    "svg": ("SVG", "image/svg+xml", "#FFB13B", "S"),
    "png": ("PNG", "image/png", "#4B8B3B", "P"),
    "jpg": ("JPG", "image/jpeg", "#6554C0", "J"),
}

_IMAGE_DATA_URI = re.compile(r"data:image/(png|jpeg|jpg);base64,([A-Za-z0-9+/=\r\n]+)", re.I)
_SVG_DATA_URI = re.compile(r"data:image/svg\+xml(?:;charset=[^;,]+)?;base64,([A-Za-z0-9+/=\r\n]+)", re.I)
_SVG_FENCE = re.compile(r"```(?:svg|xml)?\s*\n(.*?)\n```", re.I | re.S)
_SVG_MARKUP = re.compile(r"<svg\b.*?</svg\s*>", re.I | re.S)
_INTERNAL_IMAGE_URL = re.compile(r"(?:(?:https?://[^/\s)]+)?)(/api/v1/files/[A-Za-z0-9_-]+/content)(?:[?#][^\s)]*)?", re.I)
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_SVG_BYTES = 2 * 1024 * 1024


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_strings(child)


def _safe_svg(source: str) -> bytes:
    raw = source.strip().encode("utf-8")
    if len(raw) > _MAX_SVG_BYTES:
        raise ValueError("SVG превышает лимит 2 МБ.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"Некорректный SVG/XML: {exc}.") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError("В ответе не найден корневой элемент <svg>.")
    forbidden = {"script", "foreignobject", "iframe", "object", "embed"}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() in forbidden:
            raise ValueError("SVG содержит активный/встраиваемый элемент; экспорт отклонён.")
        text = (element.text or "").lower()
        if "javascript:" in text or "@import" in text or re.search(r"url\(\s*['\"]?\s*(?:https?:|//)", text):
            raise ValueError("SVG содержит исполняемый код или внешние ресурсы; экспорт отклонён.")
        for key, value in element.attrib.items():
            local = key.rsplit("}", 1)[-1].lower()
            lowered = value.strip().lower()
            if local.startswith("on") or "javascript:" in lowered or "data:text/html" in lowered:
                raise ValueError("SVG содержит исполняемый атрибут или опасную ссылку; экспорт отклонён.")
            if re.search(r"url\(\s*['\"]?\s*(?:https?:|//)", lowered):
                raise ValueError("Внешние ресурсы в SVG не поддерживаются.")
            if local in {"href", "src"} and lowered and not lowered.startswith("#"):
                raise ValueError("Внешние ссылки в SVG не поддерживаются.")
    return raw + (b"\n" if not raw.endswith(b"\n") else b"")


def _embedded_image(strings, wanted: str) -> Optional[bytes]:
    for text in strings:
        for match in _IMAGE_DATA_URI.finditer(text):
            subtype, encoded = match.groups()
            kind = "png" if subtype.lower() == "png" else "jpg"
            if kind != wanted:
                continue
            if len(encoded) > ((_MAX_IMAGE_BYTES + 2) // 3) * 4 + 1024:
                raise ValueError("Изображение превышает лимит 20 МБ.")
            try:
                data = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"Встроенные данные {kind.upper()} повреждены.") from exc
            if not data or len(data) > _MAX_IMAGE_BYTES:
                raise ValueError("Изображение пустое или превышает лимит 20 МБ.")
            if kind == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Встроенные данные не имеют сигнатуру PNG.")
            if kind == "jpg" and not data.startswith(b"\xff\xd8\xff"):
                raise ValueError("Встроенные данные не имеют сигнатуру JPEG.")
            return data
    return None


def _internal_image_url(message: dict) -> Optional[str]:
    for text in _walk_strings(message):
        for match in _INTERNAL_IMAGE_URL.finditer(text):
            candidate = match.group(0).rstrip(".,;!)]}")
            parsed = urllib.parse.urlsplit(candidate)
            path = parsed.path if parsed.scheme else candidate.split("?", 1)[0].split("#", 1)[0]
            if path == match.group(1):
                return candidate
    return None


def _image_payload(message: dict, fmt: str):
    strings = list(_walk_strings(message))
    if fmt == "svg":
        for text in strings:
            data_uri = _SVG_DATA_URI.search(text)
            if data_uri:
                encoded = data_uri.group(1)
                if len(encoded) > ((_MAX_SVG_BYTES + 2) // 3) * 4 + 32:
                    raise ValueError("SVG превышает лимит 2 МБ.")
                try:
                    source = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True).decode("utf-8")
                except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
                    raise ValueError("Встроенный SVG повреждён или не является UTF-8.") from exc
                return _safe_svg(source)
            match = _SVG_FENCE.search(text) or _SVG_MARKUP.search(text)
            if match:
                return _safe_svg(match.group(1) if match.lastindex else match.group(0))
    else:
        data = _embedded_image(strings, fmt)
        if data is not None:
            return data
    path = _internal_image_url(message)
    if path:
        return path
    if fmt == "svg":
        raise ValueError("Не найден SVG-код или файл Open WebUI. Поддерживаются блок ```svg``` и /api/v1/files/{id}/content.")
    raise ValueError(f"Нет встроенного base64 {fmt.upper()} или внутреннего файла Open WebUI. Внешние URL не загружаются.")


def _has_image_payload(message: dict, fmt: str) -> bool:
    try:
        _image_payload(message, fmt)
        return True
    except ValueError:
        return False


def _image_title(message: dict) -> str:
    files = message.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                for key in ("filename", "name"):
                    if isinstance(item.get(key), str) and item[key].strip():
                        return _slug(item[key].rsplit(".", 1)[0])
    for text in _walk_strings(message.get("content", "")):
        alt = re.search(r"!\[([^\]]{1,100})\]\(", text)
        if alt:
            return _slug(alt.group(1))
        heading = re.search(r"^#{1,3}\s+(.+)$", text, re.M)
        if heading:
            return _slug(heading.group(1))
    return "image"


def _download_file_js(path: str, filename: str, fmt: str) -> str:
    url = json.dumps(path)
    name = json.dumps(filename)
    if fmt == "svg":
        validator = r'''if(blob.size>2097152)throw Error("SVG больше 2 МБ");const text=await blob.text();const doc=new DOMParser().parseFromString(text,"image/svg+xml");const root=doc.documentElement;if(root.localName!=="svg"||doc.querySelector("parsererror"))throw Error("Ответ не является корректным SVG");if(doc.querySelector("script,foreignObject,iframe,object,embed"))throw Error("SVG содержит активное содержимое");for(const el of doc.querySelectorAll("*")){if(el.localName.toLowerCase()==="style"&&/javascript:|url\(\s*['\"]?\s*(?:https?:|\/\/)|@import/i.test(el.textContent))throw Error("SVG содержит внешние стили или код");for(const attr of el.attributes){const v=attr.value.trim().toLowerCase();if(attr.name.toLowerCase().startsWith("on")||/javascript:|data:text\/html|url\(\s*['\"]?\s*(?:https?:|\/\/)/.test(v))throw Error("SVG содержит небезопасную ссылку");if(["href","src"].includes(attr.localName.toLowerCase())&&v&&!v.startsWith("#"))throw Error("SVG содержит внешнюю ссылку");}}blob=new Blob([new XMLSerializer().serializeToString(doc)],{type:"image/svg+xml"});'''
    elif fmt == "png":
        validator = '''const b=new Uint8Array(await blob.slice(0,8).arrayBuffer());if(blob.size<8||b[0]!==137||b[1]!==80||b[2]!==78||b[3]!==71||b[4]!==13||b[5]!==10||b[6]!==26||b[7]!==10)throw Error("Файл не является PNG");'''
    else:
        validator = '''const b=new Uint8Array(await blob.slice(0,3).arrayBuffer());if(blob.size<3||b[0]!==255||b[1]!==216||b[2]!==255)throw Error("Файл не является JPEG");'''
    return f'''(async()=>{{try{{const u=new URL({url},location.href);if(u.origin!==location.origin||!/^\\/api\\/v1\\/files\\/[A-Za-z0-9_-]+\\/content$/.test(u.pathname))throw Error("Разрешены только внутренние файлы Open WebUI");const r=await fetch(u.href,{{credentials:"same-origin"}});if(!r.ok)throw Error("Не удалось получить файл (HTTP "+r.status+")");let blob=await r.blob();if(blob.size>20971520)throw Error("Файл больше 20 МБ");{validator}const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download={name};document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1000);}}catch(e){{console.error("Image export failed:",e);window.dispatchEvent(new CustomEvent("open-webui-toast",{{detail:{{type:"error",content:"Экспорт изображения: "+e.message}}}}));}}}})();'''


def _icon(color: str, letter: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="2" width="18" height="20" rx="3" fill="{color}"/>'
        f'<text x="12" y="17" font-family="Arial" font-size="12" font-weight="bold" fill="#fff" text-anchor="middle">{letter}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _js_download(b64: str, name: str, mime: str) -> str:
    return f"""
(function() {{
  const bin = atob("{b64}");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], {{type: "{mime}"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = {name!r};
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {{ URL.revokeObjectURL(a.href); a.remove(); }}, 1000);
}})();
"""


def _slug(text: str) -> str:
    s = re.sub(r"[^\wЀ-ӿ一-鿿-]+", "_", text, flags=re.U).strip("_")
    return (s or "export")[:40]


class Action:
    class Valves(BaseModel):
        scope: str = Field(
            default="last_message",
            description="last_message = the message whose button was clicked (or the last assistant reply); all_messages = the whole chat",
        )
        pdf_font_dir: str = Field(default="", description="Override folder with NotoSans-*.ttf (normally auto-detected)")

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.actions = [
            {"id": k, "name": f"{v[0]}", "icon_url": _icon(v[2], v[3])} for k, v in FORMATS.items()
        ]

    async def _notify(self, emitter: Any, kind: str, text: str) -> None:
        if emitter:
            await emitter({"type": "notification", "data": {"type": kind, "content": text}})

    async def action(
        self,
        body: dict,
        __id__: Optional[str] = None,
        __event_emitter__: Any = None,
        __event_call__: Any = None,
        **_: Any,
    ) -> Optional[dict]:
        fmt = (__id__ or "docx").lower()
        if fmt not in FORMATS:
            await self._notify(__event_emitter__, "error", f"Неизвестный формат: {fmt}")
            return None
        msgs = list(body.get("messages") or [])
        if fmt in ("svg", "png", "jpg"):
            candidates = list(reversed(msgs)) if self.valves.scope == "all_messages" else []
            if not candidates:
                mid = body.get("id")
                picked = [m for m in msgs if mid and m.get("id") == mid]
                candidates = picked or [m for m in reversed(msgs) if m.get("role") == "assistant"][:1] or msgs[-1:]
            message = next((m for m in candidates if _has_image_payload(m, fmt)), None)
            if message is None:
                await self._notify(__event_emitter__, "warning", f"Не найдено изображение формата {fmt.upper()} в сообщении.")
                return None
            try:
                payload = _image_payload(message, fmt)
            except ValueError as e:
                await self._notify(__event_emitter__, "warning", str(e))
                return None
            name = f"{_image_title(message)}-{time.strftime('%Y%m%d-%H%M')}.{fmt}"
            code = (
                _download_file_js(payload, name, fmt)
                if isinstance(payload, str)
                else _js_download(base64.b64encode(payload).decode("ascii"), name, FORMATS[fmt][1])
            )
            if __event_emitter__:
                await __event_emitter__({"type": "execute", "data": {"code": code}})
                await self._notify(__event_emitter__, "success", f"Скачивается {name}")
            elif __event_call__:
                await __event_call__({"type": "execute", "data": {"code": code}})
            return None
        if self.valves.scope != "all_messages":
            mid = body.get("id")
            picked = [m for m in msgs if mid and m.get("id") == mid]
            if not picked:
                picked = [m for m in reversed(msgs) if m.get("role") == "assistant"][:1] or msgs[-1:]
            msgs = picked
        md = "\n\n".join(
            (f"## {'Вы' if m.get('role') == 'user' else 'Модель'}\n\n" if self.valves.scope == "all_messages" else "")
            + _clean(_content(m))
            for m in msgs
        )
        if not md.strip():
            await self._notify(__event_emitter__, "warning", "Нет текста для экспорта")
            return None
        try:
            blocks = parse_markdown(md)
            title = _title_of(blocks)
            if fmt == "docx":
                raw = build_docx(blocks, title)
            elif fmt == "xlsx":
                raw = build_xlsx(blocks, title)
            elif fmt == "pptx":
                raw = build_pptx(blocks, title)
            elif fmt == "vsdx":
                raw = build_vsdx(blocks, title)
            elif fmt == "md":
                raw = (md.strip() + chr(10)).encode("utf-8")  # the answer as-is (think blocks removed)
            elif fmt == "txt":
                raw = build_txt(blocks)
            elif fmt == "csv":
                raw = build_csv(blocks)
            elif fmt == "pdf":
                # Open WebUI 0.11.3/0.11.4 images do not provide a stable PDF
                # font/runtime.  Never emit a PDF with substituted Cyrillic
                # glyphs ("???"); use the browser's native UTF-8 print engine.
                code = _js_print_html(build_pdf_html(blocks, title))
                if __event_emitter__:
                    await __event_emitter__({"type": "execute", "data": {"code": code}})
                    await self._notify(__event_emitter__, "info", "Открывается печать браузера: выберите «Сохранить как PDF».")
                elif __event_call__:
                    await __event_call__({"type": "execute", "data": {"code": code}})
                return None
        except ValueError as e:  # user-level problem (no tables, nothing to draw)
            await self._notify(__event_emitter__, "warning", str(e))
            return None
        except ImportError as e:
            await self._notify(
                __event_emitter__,
                "error",
                f"В этом образе Open WebUI нет библиотеки для {FORMATS[fmt][0]}: {e.name}. Обновите функцию под новую версию образа.",
            )
            return None
        except Exception as e:  # noqa: BLE001
            await self._notify(__event_emitter__, "error", f"Ошибка экспорта {FORMATS[fmt][0]}: {type(e).__name__}: {e}")
            return None
        name = f"{_slug(title)}-{time.strftime('%Y%m%d-%H%M')}.{fmt}"
        code = _js_download(base64.b64encode(raw).decode("ascii"), name, FORMATS[fmt][1])
        if __event_emitter__:
            await __event_emitter__({"type": "execute", "data": {"code": code}})
            await self._notify(__event_emitter__, "success", f"Скачивается {name} ({len(raw) // 1024} КБ)")
        elif __event_call__:
            await __event_call__({"type": "execute", "data": {"code": code}})
        return None
