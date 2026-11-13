from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "HX PDF"
RENDER_SCALE = 1.35
MIN_ZOOM_PERCENT = 25
MAX_ZOOM_PERCENT = 400
HIGHLIGHT_COLOR = QColor(55, 135, 245, 115)


def resource_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / name


class PdfPageLabel(QLabel):
    def __init__(self, page, image: QImage, scale: float, on_focus) -> None:
        super().__init__()
        self.pdf_page = page
        self.scale = scale
        self.page_height = page.get_height()
        self.on_focus = on_focus
        self.selection_start: int | None = None
        self.selection_end: int | None = None
        self.search_matches: list[tuple[int, int]] = []
        self.active_search_match: tuple[int, int] | None = None
        self._textpage = None
        self._char_boxes: dict[int, tuple[float, float, float, float]] = {}
        self._dragging = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: white; border: 1px solid #d6dde7;")
        self.setPixmap(QPixmap.fromImage(image))
        self.setFixedSize(image.size())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._copy_shortcuts = []
        for key in (QKeySequence.StandardKey.Copy, QKeySequence.StandardKey.Cut):
            shortcut = QShortcut(key, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self.copy_selection)
            self._copy_shortcuts.append(shortcut)

    def _get_textpage(self):
        if self._textpage is None:
            self._textpage = self.pdf_page.get_textpage()
        return self._textpage

    def _char_at(self, point) -> int | None:
        x = point.x() / self.scale
        y = self.page_height - point.y() / self.scale
        try:
            return self._get_textpage().get_index(
                x, y, x_tol=max(2.5, 5.0 / self.scale), y_tol=max(3.0, 6.0 / self.scale)
            )
        except Exception:
            return None

    def _char_rect(self, textpage, index: int):
        if index not in self._char_boxes:
            try:
                self._char_boxes[index] = textpage.get_charbox(index)
            except Exception:
                self._char_boxes[index] = (0.0, 0.0, 0.0, 0.0)
        left, bottom, right, top = self._char_boxes[index]
        if right <= left or top <= bottom:
            return None
        return (left * self.scale, (self.page_height - top) * self.scale,
                (right - left) * self.scale, (top - bottom) * self.scale)

    def _paint_span(self, painter: QPainter, textpage, span: tuple[int, int], color: QColor) -> None:
        start, count = span
        line_rects: list[list[float]] = []
        for index in range(start, start + count):
            rect = self._char_rect(textpage, index)
            if rect is None:
                continue
            x, y, width, height = rect
            if line_rects:
                last = line_rects[-1]
                overlap = min(last[1] + last[3], y + height) - max(last[1], y)
                same_line = overlap >= min(last[3], height) * 0.25
                gap = x - (last[0] + last[2])
                gap_limit = max(5.0, min(last[3], height) * 0.85)
                if same_line and gap <= gap_limit:
                    right = max(last[0] + last[2], x + width)
                    bottom = max(last[1] + last[3], y + height)
                    last[0] = min(last[0], x)
                    last[1] = min(last[1], y)
                    last[2] = right - last[0]
                    last[3] = bottom - last[1]
                    continue
            line_rects.append([x, y, width, height])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x, y, width, height in line_rects:
            painter.drawRoundedRect(x - 1, y, width + 2, height, 2.5, 2.5)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.search_matches and self.selection_start is None:
            return
        try:
            textpage = self._get_textpage()
        except Exception:
            return
        painter = QPainter(self)
        for span in self.search_matches:
            self._paint_span(painter, textpage, span, HIGHLIGHT_COLOR)
        if self.selection_start is not None and self.selection_end is not None:
            start = min(self.selection_start, self.selection_end)
            count = abs(self.selection_end - self.selection_start) + 1
            self._paint_span(painter, textpage, (start, count), HIGHLIGHT_COLOR)
        painter.end()

    def set_search_matches(self, matches: list[tuple[int, int]], active: tuple[int, int] | None) -> None:
        self.search_matches = matches
        self.active_search_match = active
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.on_focus(self)
            index = self._char_at(event.position())
            self._dragging = index is not None
            self.selection_start = index
            self.selection_end = index
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            index = self._char_at(event.position())
            if index is not None:
                self.selection_end = index
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                index = self._char_at(event.position())
                if index is not None:
                    self.selection_end = index
                    self.update()
            self._dragging = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> str:
        if self.selection_start is None or self.selection_end is None:
            return ""
        start = min(self.selection_start, self.selection_end)
        count = abs(self.selection_end - self.selection_start) + 1
        try:
            text = self._get_textpage().get_text_range(start, count).replace("\x00", "")
            if text:
                QApplication.clipboard().setText(text)
            return text
        except Exception:
            return ""

    def close_textpage(self) -> None:
        if self._textpage is not None:
            self._textpage.close()
            self._textpage = None
        self._char_boxes.clear()


class PdfReaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Đọc và in tài liệu PDF")
        self.setWindowIcon(QIcon(str(resource_path("app_icon.png"))))
        self.resize(1180, 820)
        self.setMinimumSize(760, 560)
        self.document = None
        self.file_path: Path | None = None
        self.page_index = 0
        self.zoom = RENDER_SCALE
        self.page_text: dict[int, str] = {}
        self.search_results: list[tuple[int, int, int]] = []
        self.search_position = -1
        self.last_search_query = ""
        self.page_labels: list[QLabel] = []
        self.active_page_label: PdfPageLabel | None = None
        self._build_ui()
        self._build_actions()
        self._set_empty_state()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #eef2f7; }
            QToolBar { background: #ffffff; border: 0; border-bottom: 1px solid #dce3ec; spacing: 6px; padding: 8px; }
            QToolButton, QPushButton { color: #26354a; background: #ffffff; border: 1px solid #d7e0eb; border-radius: 8px; padding: 7px 12px; }
            QToolButton:hover, QPushButton:hover { background: #f0f6ff; border-color: #9bbce8; }
            QLineEdit, QSpinBox { background: white; border: 1px solid #d7e0eb; border-radius: 7px; padding: 6px 8px; }
            QStatusBar { background: #ffffff; border-top: 1px solid #dce3ec; color: #536276; }
        """)

        toolbar = QToolBar("Thanh công cụ")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_button = QPushButton("Mở PDF")
        open_button.clicked.connect(self.open_dialog)
        toolbar.addWidget(open_button)
        self.print_button = QPushButton("In")
        self.print_button.clicked.connect(self.print_document)
        toolbar.addWidget(self.print_button)
        toolbar.addSeparator()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Tìm trong tài liệu")
        self.search_box.setFixedWidth(220)
        self.search_box.returnPressed.connect(self.search_next)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.setToolTip("Enter: kết quả tiếp theo • Shift+Enter: kết quả trước")
        self.search_previous_shortcut = QShortcut(QKeySequence("Shift+Return"), self.search_box)
        self.search_previous_shortcut.activated.connect(self.search_previous)
        toolbar.addWidget(self.search_box)
        toolbar.addSeparator()

        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setFixedWidth(72)
        self.page_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_prev_button = QPushButton("−")
        self.page_prev_button.setToolTip("Về trang trước (−1 trang)")
        self.page_prev_button.setEnabled(False)
        self.page_prev_button.clicked.connect(lambda: self.go_to_page(self.page_index - 1))
        toolbar.addWidget(self.page_prev_button)
        self.page_input.valueChanged.connect(lambda value: self.go_to_page(value - 1))
        toolbar.addWidget(self.page_input)
        self.page_next_button = QPushButton("+")
        self.page_next_button.setToolTip("Đến trang tiếp theo (+1 trang)")
        self.page_next_button.setEnabled(False)
        self.page_next_button.clicked.connect(lambda: self.go_to_page(self.page_index + 1))
        toolbar.addWidget(self.page_next_button)
        self.page_total = QLabel("/ 0")
        toolbar.addWidget(self.page_total)
        toolbar.addSeparator()

        zoom_out = QPushButton("−")
        zoom_out.setToolTip("Thu nhỏ")
        zoom_out.clicked.connect(lambda: self.change_zoom(-10))
        toolbar.addWidget(zoom_out)
        self.zoom_input = QSpinBox()
        self.zoom_input.setRange(MIN_ZOOM_PERCENT, MAX_ZOOM_PERCENT)
        self.zoom_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.zoom_input.setSuffix("%")
        self.zoom_input.setValue(100)
        self.zoom_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_input.setKeyboardTracking(False)
        self.zoom_input.setToolTip("Nhập phần trăm thu phóng rồi nhấn Enter")
        self.zoom_input.setFixedWidth(82)
        self.zoom_input.valueChanged.connect(lambda percent: self.set_zoom(RENDER_SCALE * percent / 100.0))
        toolbar.addWidget(self.zoom_input)
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Phóng to")
        zoom_in.clicked.connect(lambda: self.change_zoom(10))
        toolbar.addWidget(zoom_in)
        fit_button = QPushButton("Vừa trang")
        fit_button.clicked.connect(self.fit_page)
        toolbar.addWidget(fit_button)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setStyleSheet("QScrollArea { border: 0; background: #e8edf4; }")
        self.pages_widget = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_widget)
        self.pages_layout.setContentsMargins(20, 20, 20, 20)
        self.pages_layout.setSpacing(18)
        self.scroll.setWidget(self.pages_widget)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_page_from_scroll)
        self.setCentralWidget(self.scroll)
        self.setStatusBar(QStatusBar())

    def _build_actions(self) -> None:
        shortcuts = [
            ("Ctrl+O", self.open_dialog),
            ("Ctrl+P", self.print_document),
            ("Ctrl+F", lambda: self.search_box.setFocus()),
            ("F3", self.search_next),
            ("Shift+F3", self.search_previous),
            ("Left", lambda: self.go_to_page(self.page_index - 1)),
            ("Right", lambda: self.go_to_page(self.page_index + 1)),
            ("Ctrl+Plus", lambda: self.change_zoom(10)),
            ("Ctrl+Minus", lambda: self.change_zoom(-10)),
        ]
        for shortcut, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def _set_empty_state(self) -> None:
        self.empty_label = QLabel("Kéo thả tệp PDF vào cửa sổ hoặc bấm ‘Mở PDF’ để bắt đầu")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumSize(QSize(720, 520))
        self.empty_label.setStyleSheet("background:#ffffff; color:#617188; font-size:18px; border:1px solid #d6dde7; border-radius:10px;")
        self.pages_layout.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.statusBar().showMessage("Tệp được mở trực tiếp trên máy tính.")
        self.print_button.setEnabled(False)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            candidate = Path(urls[0].toLocalFile())
            if candidate.suffix.lower() == ".pdf":
                self.open_file(candidate)

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Mở tài liệu PDF", "", "Tài liệu PDF (*.pdf)")
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        try:
            new_document = pdfium.PdfDocument(str(path))
            new_document.init_forms()
            if len(new_document) == 0:
                raise ValueError("Tài liệu không có trang nào.")
        except Exception as exc:
            password, accepted = QInputDialog.getText(
                self,
                "PDF có mật khẩu?",
                "Nếu tài liệu được bảo vệ, nhập mật khẩu để mở:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not password:
                QMessageBox.critical(self, "Không mở được PDF", f"Không thể mở tệp này.\n\nChi tiết: {exc}")
                return
            try:
                new_document = pdfium.PdfDocument(str(path), password=password)
                new_document.init_forms()
                if len(new_document) == 0:
                    raise ValueError("Tài liệu không có trang nào.")
            except Exception as password_exc:
                QMessageBox.critical(self, "Không mở được PDF", f"Mật khẩu không đúng hoặc tệp bị lỗi.\n\nChi tiết: {password_exc}")
                return

        if self.document is not None:
            self._clear_page_widgets()
            self.document.close()
        self.document = new_document
        self.file_path = path
        self.page_index = 0
        self.page_prev_button.setEnabled(len(self.document) > 1)
        self.page_next_button.setEnabled(len(self.document) > 1)
        self.page_text.clear()
        self.search_results.clear()
        self.search_position = -1
        self.last_search_query = ""
        self.page_input.blockSignals(True)
        self.page_input.setMaximum(len(self.document))
        self.page_input.setValue(1)
        self.page_input.blockSignals(False)
        self.page_total.setText(f"/ {len(self.document)}")
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self.print_button.setEnabled(True)
        self.zoom = RENDER_SCALE
        self.render_page()
        self.statusBar().showMessage(f"{path.name}  •  {len(self.document)} trang  •  Tệp không rời khỏi máy tính")

    def render_page(self) -> None:
        if self.document is None:
            return
        self._clear_page_widgets()
        for index in range(len(self.document)):
            page = self.document[index]
            bitmap = page.render(scale=self.zoom, rotation=0, draw_annots=True, may_draw_forms=True)
            pil_image = bitmap.to_pil().convert("RGB")
            raw = pil_image.tobytes("raw", "RGB")
            image = QImage(raw, pil_image.width, pil_image.height, pil_image.width * 3, QImage.Format.Format_RGB888).copy()
            label = PdfPageLabel(page, image, self.zoom, self._set_active_page_label)
            self.pages_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.page_labels.append(label)
        self.page_input.blockSignals(True)
        self.page_input.setValue(self.page_index + 1)
        self.page_input.blockSignals(False)
        self.zoom_input.blockSignals(True)
        self.zoom_input.setValue(round(self.zoom / RENDER_SCALE * 100))
        self.zoom_input.blockSignals(False)
        self._apply_search_markers()
        QTimer.singleShot(0, lambda: self._scroll_to_page(self.page_index))

    def _clear_page_widgets(self) -> None:
        self.page_labels.clear()
        self.active_page_label = None
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if isinstance(widget, PdfPageLabel):
                    widget.close_textpage()
                widget.deleteLater()

    def _set_active_page_label(self, label: PdfPageLabel) -> None:
        self.active_page_label = label

    def _scroll_to_page(self, index: int) -> None:
        if not self.page_labels:
            return
        index = max(0, min(index, len(self.page_labels) - 1))
        self.scroll.verticalScrollBar().setValue(self.page_labels[index].y() - 20)

    def _sync_page_from_scroll(self, value: int) -> None:
        if not self.page_labels:
            return
        center = value + self.scroll.viewport().height() / 2
        index = min(
            range(len(self.page_labels)),
            key=lambda i: abs(self.page_labels[i].geometry().center().y() - center),
        )
        self.page_index = index
        self.page_input.blockSignals(True)
        self.page_input.setValue(index + 1)
        self.page_input.blockSignals(False)
        self._update_page_buttons()

    def go_to_page(self, index: int) -> None:
        if self.document is None:
            return
        self.page_index = max(0, min(index, len(self.document) - 1))
        self.page_input.blockSignals(True)
        self.page_input.setValue(self.page_index + 1)
        self.page_input.blockSignals(False)
        self._update_page_buttons()
        self._scroll_to_page(self.page_index)

    def _update_page_buttons(self) -> None:
        has_document = self.document is not None
        self.page_prev_button.setEnabled(has_document and self.page_index > 0)
        self.page_next_button.setEnabled(has_document and self.page_index < len(self.document) - 1)

    def change_zoom(self, delta_percent: int) -> None:
        new_percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, self.zoom_input.value() + delta_percent))
        self.set_zoom(RENDER_SCALE * new_percent / 100.0)

    def set_zoom(self, value: float) -> None:
        self.zoom = max(RENDER_SCALE * MIN_ZOOM_PERCENT / 100.0,
                        min(value, RENDER_SCALE * MAX_ZOOM_PERCENT / 100.0))
        self.render_page()

    def fit_page(self) -> None:
        if self.document is None:
            return
        width = self.document[self.page_index].get_width() or 595
        available = max(400, self.scroll.viewport().width() - 40)
        self.set_zoom(min(available / width, RENDER_SCALE * MAX_ZOOM_PERCENT / 100.0))

    def copy_selected_text(self) -> None:
        label = self.active_page_label
        if label is None:
            self.statusBar().showMessage("Hãy kéo chọn phần chữ trên trang PDF trước.")
            return
        text = label.copy_selection()
        if not text:
            self.statusBar().showMessage("Chưa có chữ được chọn để sao chép.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Đã sao chép {len(text)} ký tự.")

    def _text_for_page(self, index: int) -> str:
        if index not in self.page_text:
            page = self.document[index]
            textpage = page.get_textpage()
            self.page_text[index] = textpage.get_text_range()
            textpage.close()
        return self.page_text[index]

    def _apply_search_markers(self) -> None:
        matches_by_page: dict[int, list[tuple[int, int]]] = {}
        for page_index, char_index, char_count in self.search_results:
            matches_by_page.setdefault(page_index, []).append((char_index, char_count))
        active = None
        if 0 <= self.search_position < len(self.search_results):
            active = self.search_results[self.search_position]
        for page_index, label in enumerate(self.page_labels):
            active_span = (active[1], active[2]) if active and active[0] == page_index else None
            label.set_search_matches(matches_by_page.get(page_index, []), active_span)

    def _on_search_text_changed(self, text: str) -> None:
        query = text.strip().casefold()
        if query == self.last_search_query:
            return
        self.search_results.clear()
        self.search_position = -1
        self.last_search_query = ""
        self._apply_search_markers()

    def _find_all(self) -> None:
        if self.document is None:
            return
        query = self.search_box.text().strip().casefold()
        self.search_results = []
        self.search_position = -1
        self.last_search_query = query
        if not query:
            self._apply_search_markers()
            self.statusBar().showMessage("Nhập từ khóa để tìm trong tài liệu.")
            return
        for page_index in range(len(self.document)):
            textpage = self.document[page_index].get_textpage()
            searcher = textpage.search(query, match_case=False, match_whole_word=False)
            try:
                while True:
                    result = searcher.get_next()
                    if result is None:
                        break
                    char_index, char_count = result
                    self.search_results.append((page_index, char_index, char_count))
            finally:
                searcher.close()
                textpage.close()
        self._apply_search_markers()
        if not self.search_results:
            self.statusBar().showMessage("Không tìm thấy nội dung phù hợp.")
            return
        self.search_position = 0
        self._show_search_result()

    def _show_search_result(self) -> None:
        if not self.search_results:
            return
        page_index, _, _ = self.search_results[self.search_position]
        self._apply_search_markers()
        self.go_to_page(page_index)
        self.statusBar().showMessage(f"Kết quả {self.search_position + 1}/{len(self.search_results)} — trang {page_index + 1}")

    def search_next(self) -> None:
        query = self.search_box.text().strip().casefold()
        if not self.search_results or not query or query != self.last_search_query:
            self._find_all()
            return
        self.search_position = (self.search_position + 1) % len(self.search_results)
        self._show_search_result()

    def search_previous(self) -> None:
        query = self.search_box.text().strip().casefold()
        if not self.search_results or not query or query != self.last_search_query:
            self._find_all()
            return
        self.search_position = (self.search_position - 1) % len(self.search_results)
        self._show_search_result()

    def print_document(self) -> None:
        if self.document is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Cấu hình in PDF")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return

        first = printer.fromPage() - 1 if printer.fromPage() > 0 else 0
        last = printer.toPage() - 1 if printer.toPage() > 0 else len(self.document) - 1
        first = max(0, min(first, len(self.document) - 1))
        last = max(first, min(last, len(self.document) - 1))
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Không thể in", "Không mở được hàng đợi in.")
            return
        try:
            for index in range(first, last + 1):
                if index > first:
                    printer.newPage()
                pdf_page = self.document[index]
                dpi = printer.resolution()
                bitmap = pdf_page.render(scale=dpi / 72.0, rotation=0, draw_annots=True, may_draw_forms=True)
                pil_image = bitmap.to_pil().convert("RGB")
                raw = pil_image.tobytes("raw", "RGB")
                qimage = QImage(raw, pil_image.width, pil_image.height, pil_image.width * 3, QImage.Format.Format_RGB888).copy()
                target = printer.pageRect(QPrinter.Unit.DevicePixel)
                scaled = qimage.scaled(int(target.width()), int(target.height()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                x = int(target.x() + (target.width() - scaled.width()) / 2)
                y = int(target.y() + (target.height() - scaled.height()) / 2)
                painter.drawImage(x, y, scaled)
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi khi in", str(exc))
        finally:
            painter.end()
        self.statusBar().showMessage("Tài liệu đã được gửi tới máy in.")


def register_pdf_open_with() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg

    exe_path = str(Path(sys.executable).resolve())
    exe_name = Path(exe_path).name
    classes = r"Software\Classes"
    app_key = classes + rf"\Applications\{exe_name}"
    prog_id = "HXPDF.Document"
    command = f'"{exe_path}" "%1"'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key) as key:
        winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, "HX PDF")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key + r"\SupportedTypes") as key:
        winreg.SetValueEx(key, ".pdf", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key + r"\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "HX PDF document")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}\DefaultIcon") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{exe_path}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + r"\.pdf\OpenWithProgids") as key:
        winreg.SetValueEx(key, prog_id, 0, winreg.REG_SZ, "")

    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def main() -> int:
    input_files = list(sys.argv[1:])
    register_pdf_open_with()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(resource_path("app_icon.png"))))
    window = PdfReaderWindow()
    window.show()
    for argument in input_files:
        candidate = Path(argument.strip('"'))
        if candidate.suffix.lower() == ".pdf" and candidate.is_file():
            QTimer.singleShot(0, lambda path=candidate: window.open_file(path))
            break
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
