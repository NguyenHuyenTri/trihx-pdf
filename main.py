from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
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


APP_NAME = "PDF Reader"
RENDER_SCALE = 1.35


class PdfReaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Đọc và in tài liệu PDF")
        self.resize(1180, 820)
        self.setMinimumSize(760, 560)
        self.document = None
        self.file_path: Path | None = None
        self.page_index = 0
        self.zoom = RENDER_SCALE
        self.page_text: dict[int, str] = {}
        self.search_pages: list[int] = []
        self.search_position = -1
        self.page_labels: list[QLabel] = []
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
        toolbar.addWidget(self.search_box)
        self.search_prev_button = QPushButton("↑")
        self.search_prev_button.setToolTip("Kết quả trước")
        self.search_prev_button.clicked.connect(self.search_previous)
        toolbar.addWidget(self.search_prev_button)
        self.search_next_button = QPushButton("↓")
        self.search_next_button.setToolTip("Kết quả tiếp theo")
        self.search_next_button.clicked.connect(self.search_next)
        toolbar.addWidget(self.search_next_button)
        toolbar.addSeparator()

        self.prev_button = QPushButton("‹")
        self.prev_button.setToolTip("Trang trước")
        self.prev_button.clicked.connect(lambda: self.go_to_page(self.page_index - 1))
        toolbar.addWidget(self.prev_button)
        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setFixedWidth(72)
        self.page_input.valueChanged.connect(lambda value: self.go_to_page(value - 1))
        toolbar.addWidget(self.page_input)
        self.page_total = QLabel("/ 0")
        toolbar.addWidget(self.page_total)
        self.next_button = QPushButton("›")
        self.next_button.setToolTip("Trang tiếp theo")
        self.next_button.clicked.connect(lambda: self.go_to_page(self.page_index + 1))
        toolbar.addWidget(self.next_button)
        toolbar.addSeparator()

        zoom_out = QPushButton("−")
        zoom_out.setToolTip("Thu nhỏ")
        zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom / 1.15))
        toolbar.addWidget(zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.zoom_label)
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Phóng to")
        zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom * 1.15))
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
            ("Left", lambda: self.go_to_page(self.page_index - 1)),
            ("Right", lambda: self.go_to_page(self.page_index + 1)),
            ("Ctrl+Plus", lambda: self.set_zoom(self.zoom * 1.15)),
            ("Ctrl+Minus", lambda: self.set_zoom(self.zoom / 1.15)),
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
            self.document.close()
        self.document = new_document
        self.file_path = path
        self.page_index = 0
        self.page_text.clear()
        self.search_pages.clear()
        self.search_position = -1
        self.page_input.blockSignals(True)
        self.page_input.setMaximum(len(self.document))
        self.page_input.setValue(1)
        self.page_input.blockSignals(False)
        self.page_total.setText(f"/ {len(self.document)}")
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self.print_button.setEnabled(True)
        self.zoom = RENDER_SCALE
        self._clear_page_widgets()
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
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: white; border: 1px solid #d6dde7;")
            label.setPixmap(QPixmap.fromImage(image))
            label.setFixedSize(image.size())
            self.pages_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.page_labels.append(label)
        self.page_input.blockSignals(True)
        self.page_input.setValue(self.page_index + 1)
        self.page_input.blockSignals(False)
        self.zoom_label.setText(f"{round(self.zoom / RENDER_SCALE * 100)}%")
        self.prev_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index < len(self.document) - 1)
        QTimer.singleShot(0, lambda: self._scroll_to_page(self.page_index))

    def _clear_page_widgets(self) -> None:
        self.page_labels.clear()
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

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
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self.page_labels) - 1)

    def go_to_page(self, index: int) -> None:
        if self.document is None:
            return
        self.page_index = max(0, min(index, len(self.document) - 1))
        self.page_input.blockSignals(True)
        self.page_input.setValue(self.page_index + 1)
        self.page_input.blockSignals(False)
        self.prev_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index < len(self.document) - 1)
        self._scroll_to_page(self.page_index)

    def set_zoom(self, value: float) -> None:
        self.zoom = max(0.35, min(value, 4.0))
        self.render_page()

    def fit_page(self) -> None:
        if self.document is None:
            return
        width = self.document[self.page_index].get_width() or 595
        available = max(400, self.scroll.viewport().width() - 40)
        self.zoom = min(available / width, 2.5)
        self.render_page()

    def _text_for_page(self, index: int) -> str:
        if index not in self.page_text:
            page = self.document[index]
            textpage = page.get_textpage()
            self.page_text[index] = textpage.get_text_range()
            textpage.close()
        return self.page_text[index]

    def _find_all(self) -> None:
        if self.document is None:
            return
        query = self.search_box.text().strip().casefold()
        self.search_pages = []
        self.search_position = -1
        if not query:
            self.statusBar().showMessage("Nhập từ khóa để tìm trong tài liệu.")
            return
        for index in range(len(self.document)):
            if query in self._text_for_page(index).casefold():
                self.search_pages.append(index)
        if not self.search_pages:
            self.statusBar().showMessage("Không tìm thấy nội dung phù hợp.")
            return
        self.search_position = 0
        self._show_search_result()

    def _show_search_result(self) -> None:
        if not self.search_pages:
            return
        index = self.search_pages[self.search_position]
        self.go_to_page(index)
        self.statusBar().showMessage(f"Kết quả {self.search_position + 1}/{len(self.search_pages)} — trang {index + 1}")

    def search_next(self) -> None:
        if not self.search_pages or not self.search_box.text().strip():
            self._find_all()
            return
        self.search_position = (self.search_position + 1) % len(self.search_pages)
        self._show_search_result()

    def search_previous(self) -> None:
        if not self.search_pages or not self.search_box.text().strip():
            self._find_all()
            return
        self.search_position = (self.search_position - 1) % len(self.search_pages)
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = PdfReaderWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
