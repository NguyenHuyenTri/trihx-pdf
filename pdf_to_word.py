"""Local, editable export. The source PDF is only ever opened for reading."""
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack

import pdfplumber
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_PAGE_MARGIN = 24
_CELL_VERTICAL_PADDING = 1.25


def _text(value):
    return _CONTROL.sub("", value or "")


def _ocr_engine():
    executable = shutil.which("tesseract")
    if not executable and os.name == "nt":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(key)
            if root:
                candidate = Path(root) / "Tesseract-OCR" / "tesseract.exe"
                if candidate.is_file():
                    executable = str(candidate)
                    break
    if not executable:
        raise RuntimeError("PDF có trang scan. Hãy cài Tesseract OCR 5 cùng gói tiếng Việt (vie) rồi thử lại.")
    return executable


def _ocr(image, engine):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    result = subprocess.run([engine, "stdin", "stdout", "--dpi", "300", "-l", "vie", "--psm", "3"],
                            input=buffer.getvalue(), capture_output=True, timeout=180,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Tesseract không xử lý được ảnh. Kiểm tra dữ liệu tiếng Việt (vie.traineddata).")
    return _text(result.stdout.decode("utf-8", errors="replace")).strip()


def _render(source, index, scale):
    page = source[index]
    try:
        bitmap = page.render(scale=scale, draw_annots=True, may_draw_forms=True)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    finally:
        page.close()


def _inside(char, bounds):
    x = (char["x0"] + char["x1"]) / 2
    y = (char["top"] + char["bottom"]) / 2
    return bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]


def _add_table(word, source, content_width):
    rows = source.extract()
    if not rows or not any(rows):
        return
    table = word.add_table(rows=len(rows), cols=max(map(len, rows)))
    table.style = "Table Grid"
    columns = source.columns
    if len(columns) == len(table.columns):
        table.autofit = False
        left, _, right, _ = source.bbox
        factor = min(1, content_width / (right - left))
        widths = [Pt(max(10, (col.bbox[2] - col.bbox[0]) * factor)) for col in columns]
        for col, width in zip(table.columns, widths):
            col.width = width
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = width
    indent = OxmlElement("w:tblInd")
    indent.set(qn("w:type"), "dxa")
    left_indent = max(0, source.bbox[0] - source.page.bbox[0] - _PAGE_MARGIN)
    indent.set(qn("w:w"), str(round(left_indent * 20)))
    table._tbl.tblPr.insert_element_before(indent, "w:tblLayout", "w:tblLook")
    inset = OxmlElement("w:tblCellMar")
    for edge in ("top", "left", "bottom", "right"):
        item = OxmlElement(f"w:{edge}")
        item.set(qn("w:type"), "dxa")
        padding = _CELL_VERTICAL_PADDING if edge in ("top", "bottom") else 2.1
        item.set(qn("w:w"), str(round(padding * 20)))
        inset.append(item)
    table._tbl.tblPr.insert_element_before(inset, "w:tblLook")
    for row, values, original in zip(table.rows, rows, source.rows):
        height = original.bbox[3] - original.bbox[1]
        row.height = Pt(max(1, height - 2 * _CELL_VERTICAL_PADDING))
        for cell, value, bbox in zip(row.cells, values, original.cells):
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            run = paragraph.add_run(_text(value))
            chars = [char for char in source.page.chars if bbox and _inside(char, bbox) and char["text"].strip()]
            font_size = min(24, max(6, max((c["size"] for c in chars), default=10)))
            run.font.size = Pt(font_size)
            run.bold = any("bold" in char.get("fontname", "").lower() for char in chars)
            paragraph.paragraph_format.line_spacing = Pt(font_size)


def _horizontal(item):
    matrix = item.get("matrix")
    return item.get("upright", True) and (not matrix or (
        matrix[0] > 0 and abs(matrix[1]) <= abs(matrix[0]) * 0.12))


def _page_blocks(page):
    # Filled header cells can create nearly coincident edges around the actual grid.
    tables = page.find_tables({"snap_tolerance": 6})
    bounds = [table.bbox for table in tables]
    without_tables = page.filter(lambda item: item["object_type"] != "char" or
                                 not any(_inside(item, box) for box in bounds))
    blocks = [(line["top"], line["x0"], "line", line)
              for line in without_tables.extract_text_lines(return_chars=True)]
    blocks.extend((table.bbox[1], table.bbox[0], "table", table) for table in tables)
    for item in page.images:
        left, top = max(item["x0"], page.bbox[0]), max(item["top"], page.bbox[1])
        right, bottom = min(item["x1"], page.bbox[2]), min(item["bottom"], page.bbox[3])
        area = (right - left) * (bottom - top)
        if area >= 0.85 * page.width * page.height and page.chars:
            continue
        if right - left >= 6 and bottom - top >= 6:
            blocks.append((top, left, "image", (left, top, right, bottom)))
    return sorted(blocks, key=lambda block: block[:2])


def _add_line(paragraph, chars, left_margin):
    previous_right = None
    previous_style = None
    run = None
    for char in sorted(chars, key=lambda item: item["x0"]):
        value = _text(char["text"])
        font = char.get("fontname", "").lower()
        size = min(48, max(6, char.get("size", 11)))
        style = (size, "bold" in font, "italic" in font or "oblique" in font)
        gap = 0 if previous_right is None else char["x0"] - previous_right
        if gap > max(16, size * 1.4) and value.strip():
            paragraph.paragraph_format.tab_stops.add_tab_stop(Pt(char["x0"] - left_margin))
            paragraph.add_run("\t")
            run = None
        elif gap > max(1.6, size * .18) and value.strip() and run is not None and not run.text.endswith(" "):
            run.add_text(" ")
        if run is None or previous_style != style:
            run = paragraph.add_run()
            run.font.size, run.bold, run.italic = Pt(style[0]), style[1], style[2]
        run.add_text(value)
        previous_style, previous_right = style, char["x1"]


def _add_native_page(word, page, source, index, content_width):
    rendered = None
    left_margin = page.bbox[0] + _PAGE_MARGIN
    previous_bottom = page.bbox[1] + _PAGE_MARGIN
    main_page = page.filter(lambda item: item["object_type"] != "char" or _horizontal(item))
    for top, left, kind, value in _page_blocks(main_page):
        if kind == "table":
            _add_table(word, value, content_width)
            previous_bottom = value.bbox[3]
        elif kind == "line":
            p = word.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(max(0, min(100, top - previous_bottom)))
            p.paragraph_format.line_spacing = Pt(max(8, value["bottom"] - top))
            p.paragraph_format.left_indent = Pt(max(0, left - left_margin))
            p.paragraph_format.widow_control = False
            _add_line(p, value["chars"], left_margin)
            previous_bottom = value["bottom"]
        else:
            if rendered is None:
                rendered = _render(source, index, 2)
            sx, sy = rendered.width / page.width, rendered.height / page.height
            left, top, right, bottom = value
            crop = rendered.crop(((left - page.bbox[0]) * sx, (top - page.bbox[1]) * sy,
                                  (right - page.bbox[0]) * sx, (bottom - page.bbox[1]) * sy))
            image = BytesIO()
            crop.save(image, "PNG")
            image.seek(0)
            word.add_picture(image, width=Pt(min(right - left, content_width)))
            previous_bottom = bottom


def convert_pdf(source_path, destination, *, password=None, progress=None):
    import pypdfium2

    source_path, destination = Path(source_path), Path(destination)
    if destination.suffix.lower() != ".docx":
        raise ValueError("Tệp xuất phải có đuôi .docx.")
    if source_path.resolve() == destination.resolve() or (
        destination.exists() and os.path.samefile(source_path, destination)
    ):
        raise ValueError("Tệp Word phải khác tệp PDF gốc.")

    word = Document()
    normal = word.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(3)
    engine = None
    scan_pages = []
    unreadable_pages = []
    with ExitStack() as stack:
        pdf = stack.enter_context(pdfplumber.open(source_path, password=password))
        if not pdf.doc.is_extractable:
            raise PermissionError("Tệp PDF hạn chế sao chép nội dung.")
        rendered = pypdfium2.PdfDocument(source_path, password=password)
        stack.callback(rendered.close)
        rendered.init_forms()
        if not len(rendered):
            raise ValueError("Tệp PDF không có trang.")
        for index, page in enumerate(pdf.pages):
            try:
                if progress:
                    progress(index + 1, len(rendered))
                section = word.add_section(WD_SECTION.NEW_PAGE) if index else word.sections[0]
                # Word has limits on page dimensions. Keep output usable for unusual PDF sizes.
                width, height = [max(144, min(1580, edge)) for edge in (page.width, page.height)]
                section.orientation = WD_ORIENT.LANDSCAPE if width > height else WD_ORIENT.PORTRAIT
                section.page_width, section.page_height = Pt(width), Pt(height)
                section.left_margin = section.right_margin = Pt(_PAGE_MARGIN)
                section.top_margin = section.bottom_margin = Pt(_PAGE_MARGIN)
                if page.chars and any(str(char["text"]).strip() for char in page.chars):
                    _add_native_page(word, page, rendered, index, width - 2 * _PAGE_MARGIN)
                elif page.images:
                    dpi = min(300 / 72, 4000 / max(page.width, page.height))
                    if os.name == "nt" and getattr(sys, "frozen", False):
                        if engine is None:
                            from scan_ocr import windows_ocr

                            engine = windows_ocr()
                            stack.callback(engine.close)
                        text = _text(engine.recognize(_render(rendered, index, dpi), round(dpi * 72))).strip()
                    else:
                        engine = engine or _ocr_engine()
                        text = _ocr(_render(rendered, index, dpi), engine)
                    scan_pages.append(index + 1)
                    if text:
                        for line in text.splitlines():
                            word.add_paragraph(line)
                    else:
                        unreadable_pages.append(index + 1)
                        word.add_paragraph("[Không nhận dạng được chữ trên trang scan này.]")
                else:
                    word.add_paragraph()
            except Exception as exc:
                raise RuntimeError(f"Trang {index + 1}: {exc}") from exc
            finally:
                page.close()
    # Save on the same volume and replace only after generating a complete Word file.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        pending = Path(temp) / "export.docx"
        word.save(pending)
        os.replace(pending, destination)
    return scan_pages, unreadable_pages
