"""Place editable OCR text using line and word positions from Tesseract."""
from functools import lru_cache
from html.parser import HTMLParser
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import ImageFont


_BOX = re.compile(r"\bbbox (\d+) (\d+) (\d+) (\d+)")
_SIZE = re.compile(r"\bx_size ([\d.]+)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


class _Lines(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.line = None
        self.word = None
        self.spans = []
        self.bold_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("b", "strong"):
            self.bold_depth += 1
            if self.word is not None:
                self.word["bold"] = True
        if tag != "span":
            return
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        title = attributes.get("title", "")
        box = _BOX.search(title)
        kind = None
        if box and classes & {"ocr_line", "ocr_header", "ocr_textfloat", "ocr_caption"}:
            bounds = tuple(map(int, box.groups()))
            size = _SIZE.search(title)
            self.line = {"bounds": bounds, "size": float(size[1]) if size else bounds[3] - bounds[1],
                         "words": []}
            kind = "line"
        elif box and self.line is not None and "ocrx_word" in classes:
            self.word = {"bounds": tuple(map(int, box.groups())), "text": [], "bold": self.bold_depth > 0}
            kind = "word"
        self.spans.append(kind)

    def handle_data(self, data):
        if self.word is not None:
            self.word["text"].append(data)

    def handle_endtag(self, tag):
        if tag in ("b", "strong"):
            self.bold_depth = max(0, self.bold_depth - 1)
        if tag != "span" or not self.spans:
            return
        kind = self.spans.pop()
        if kind == "word" and self.word is not None:
            self.word["text"] = _CONTROL.sub("", "".join(self.word["text"])).strip()
            if self.word["text"]:
                self.line["words"].append(self.word)
            self.word = None
        elif kind == "line" and self.line is not None:
            if self.line["words"]:
                self.lines.append(self.line)
            self.line = None


@lru_cache(maxsize=2)
def _font(bold):
    names = ("timesbd.ttf", "LiberationSerif-Bold.ttf") if bold else ("times.ttf", "LiberationSerif-Regular.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, 100)
        except OSError:
            continue
    return ImageFont.load_default(size=100)


def _segments(lines, x_scale):
    for line in lines:
        current = []
        for word in line["words"]:
            gap = 0 if not current else word["bounds"][0] - current[-1]["bounds"][2]
            if gap > max(14 / x_scale, line["size"] * 1.55):
                yield current, line["size"]
                current = []
            current.append(word)
        if current:
            yield current, line["size"]


def _rows(lines):
    rows = []
    for line in sorted(lines, key=lambda line: line["bounds"][1]):
        left, top, right, bottom = line["bounds"]
        if rows:
            row = rows[-1]
            first_top, first_bottom = row[0]["bounds"][1::2]
            same_row = abs(top - first_top) <= min(bottom - top, first_bottom - first_top) * 0.45
            if same_row and all(right <= item["bounds"][0] or left >= item["bounds"][2] for item in row):
                row.append(line)
                continue
        rows.append([line])
    return rows


def _place_text(paragraph, segments, scale_x, offset_x, scale_y, margin, page_width):
    for index, (words, size) in enumerate(segments):
        left = max(margin, words[0]["bounds"][0] * scale_x + offset_x)
        right = words[-1]["bounds"][2] * scale_x + offset_x
        if index:
            paragraph.paragraph_format.tab_stops.add_tab_stop(Pt(left - margin))
            paragraph.add_run("\t")
        else:
            paragraph.paragraph_format.left_indent = Pt(left - margin)
        bold = sum(word["bold"] for word in words) * 2 >= len(words)
        text = " ".join(word["text"] for word in words)
        size = min(36, max(5, size * scale_y))
        limit = page_width - margin - 3
        if index + 1 < len(segments):
            limit = min(limit, segments[index + 1][0][0]["bounds"][0] * scale_x + offset_x - 3)
        available = max(2, min(limit, right + 4) - left)
        nominal = _font(bold).getlength(text) * size / 100
        run = paragraph.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        if nominal > available:
            compression = OxmlElement("w:w")
            compression.set(qn("w:val"), str(max(1, int(100 * available / nominal))))
            run._element.get_or_add_rPr().append(compression)


def add_scan_page(document, markup, image_size, page_size, margin):
    parsed = _Lines()
    parsed.feed(markup)
    if not parsed.lines:
        return False
    width, height = page_size
    scale_x, scale_y = width / image_size[0], height / image_size[1]
    first_left = min(line["bounds"][0] for line in parsed.lines)
    last_right = max(line["bounds"][2] for line in parsed.lines)
    scale_x = min(scale_x, (width - 2 * margin - 6) / max(1, last_right - first_left))
    offset_x = max(margin - first_left * scale_x, min(0, width - margin - 6 - last_right * scale_x))
    rows = _rows(parsed.lines)
    first_top = rows[0][0]["bounds"][1]
    last_bottom = max(line["bounds"][3] for line in parsed.lines)
    # Reserve space for Word's section break after the final line.
    scale_y = min(scale_y, (height - 2 * margin - 14) / max(1, last_bottom - first_top))
    start = min(max(margin, first_top * scale_y),
                max(margin, height - margin - 14 - (last_bottom - first_top) * scale_y))
    previous_bottom = margin
    for index, row in enumerate(rows):
        top = start + (row[0]["bounds"][1] - first_top) * scale_y
        bottom = start + (max(line["bounds"][3] for line in row) - first_top) * scale_y
        if index + 1 < len(rows):
            next_top = start + (rows[index + 1][0]["bounds"][1] - first_top) * scale_y
            bottom = min(bottom, max(top + 2, next_top))
        line_height = max(2, bottom - top)
        paragraph = document.add_paragraph()
        fmt = paragraph.paragraph_format
        fmt.widow_control = False
        fmt.space_before = Pt(max(0, top - previous_bottom))
        fmt.space_after = Pt(0)
        fmt.line_spacing = Pt(line_height)
        segments = sorted(_segments(row, scale_x), key=lambda item: item[0][0]["bounds"][0])
        _place_text(paragraph, segments, scale_x, offset_x, scale_y, margin, width)
        previous_bottom = max(top, previous_bottom) + line_height
    return True
