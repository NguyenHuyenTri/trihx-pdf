"""Local, editable export. The source PDF is only ever opened for reading."""
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack

import pdfplumber
from docx import Document
from docx.enum.section import WD_SECTION
from docx.shared import Pt

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


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
    for row, values in zip(table.rows, rows):
        for cell, value in zip(row.cells, values):
            cell.text = _text(value)


def _page_blocks(page):
    tables = page.find_tables()
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
        # PDFs with an OCR text layer often also contain a full-sheet scan.
        if area >= 0.85 * page.width * page.height and page.chars:
            continue
        if right - left >= 6 and bottom - top >= 6:
            blocks.append((top, left, "image", (left, top, right, bottom)))
    return sorted(blocks, key=lambda block: block[:2])


def _add_native_page(word, page, source, index, content_width):
    rendered = None
    previous_bottom = page.bbox[1] + 36
    for top, left, kind, value in _page_blocks(page):
        if kind == "table":
            _add_table(word, value, content_width)
            previous_bottom = value.bbox[3]
        elif kind == "line":
            p = word.add_paragraph()
            p.paragraph_format.space_before = Pt(max(0, min(24, top - previous_bottom - 3)))
            p.paragraph_format.left_indent = Pt(max(0, min(content_width / 3, left - page.bbox[0] - 36)))
            run = p.add_run(_text(value["text"]))
            previous_bottom = value["bottom"]
            chars = value["chars"]
            if chars:
                font = chars[0].get("fontname", "").lower()
                run.font.size = Pt(max(6, min(48, chars[0].get("size", 11))))
                run.bold = "bold" in font
                run.italic = "italic" in font or "oblique" in font
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
                section.page_width, section.page_height = Pt(width), Pt(height)
                section.left_margin = section.right_margin = Pt(36)
                section.top_margin = section.bottom_margin = Pt(36)
                if page.chars and any(str(char["text"]).strip() for char in page.chars):
                    _add_native_page(word, page, rendered, index, width - 72)
                elif page.images:
                    engine = engine or _ocr_engine()
                    dpi = min(300 / 72, 4000 / max(page.width, page.height))
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
