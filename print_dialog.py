"""PDF print settings, preview and Windows queue support."""
import hashlib
import re
import subprocess
import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from windows_print import configured_mode, driver_mode, driver_properties, printer_handle, printer_info, send_pdf

# Windows DMPAPER value and paper size in millimeters.
PAPERS = {9: ("A4", 210, 297), 11: ("A5", 148, 210), 8: ("A3", 297, 420),
          1: ("Letter", 215.9, 279.4), 5: ("Legal", 215.9, 355.6)}


def selected_pages(count, current, scope, specification, parity):
    if scope == 0:
        pages = list(range(count))
    elif scope == 1:
        pages = [current]
    else:
        pages = []
        for token in specification.replace("–", "-").replace("—", "-").split(","):
            match = re.fullmatch(r"\s*([0-9]{1,9})(?:\s*-\s*([0-9]{1,9}))?\s*", token)
            if not match:
                raise ValueError("Nhập các trang theo mẫu 1–3, 7.")
            first = int(match[1])
            last = int(match[2] or first)
            if not 1 <= first <= last <= count:
                raise ValueError(f"Chỉ chọn các trang từ 1 đến {count}.")
            pages.extend(range(first - 1, last))
        pages = list(dict.fromkeys(pages))
    if parity:
        pages = [page for page in pages if (page + 1) % 2 == (parity == 1)]
    if not pages:
        raise ValueError("Không có trang phù hợp với lựa chọn.")
    return pages


class PaperPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 320)
        self.image = QImage()
        self.page_mm = (0, 0)
        self.paper_mm = (210, 297)
        self.margins = (0, 0, 0, 0)
        self.actual_size = False

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.fillRect(self.rect(), QColor("#e8edf5"))
            paper_w, paper_h = self.paper_mm
            scale = min((self.width() - 32) / paper_w, (self.height() - 32) / paper_h)
            width, height = paper_w * scale, paper_h * scale
            x, y = (self.width() - width) / 2, (self.height() - height) / 2
            paper = QRectF(x, y, width, height)
            painter.fillRect(paper.translated(2, 3), QColor("#cbd4e2"))
            painter.fillRect(paper, Qt.GlobalColor.white)
            if self.image.isNull():
                return
            left, top, right, bottom = self.margins
            area = paper.adjusted(left * scale, top * scale, -right * scale, -bottom * scale)
            w, h = (value * scale for value in self.page_mm)
            ratio = 1 if self.actual_size else min(area.width() / w, area.height() / h)
            target = QRectF(area.center().x() - w * ratio / 2, area.center().y() - h * ratio / 2,
                            w * ratio, h * ratio)
            painter.setClipRect(area)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self.image)


class PdfPrintDialog(QDialog):
    def __init__(self, document, current, settings, parent=None):
        super().__init__(parent)
        self.document = document
        self.current = current
        self.settings = settings
        self.mode = None
        self.last_job = None
        self.last_error = ""
        self.last_request = None
        self.preview_position = 0
        self.preview_page = None
        self.page_list = []
        self.setWindowTitle("In PDF")
        self.resize(950, 660)
        self._build_ui()
        self._select_printer()

    @staticmethod
    def _combo(*items):
        combo = QComboBox()
        combo.addItems(items)
        return combo

    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        body.addLayout(form, 4)
        self.printers = self._combo()
        printers = QPrinterInfo.availablePrinterNames()
        self.printers.addItems(printers)
        default = QPrinterInfo.defaultPrinterName()
        self.printers.setCurrentText(default)
        form.addRow("Máy in", self.printers)
        self.driver = QLabel()
        self.driver.setWordWrap(True)
        self.driver.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.driver)
        properties = QPushButton("Thuộc tính máy in")
        properties.clicked.connect(self._properties)
        form.addRow(properties)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        form.addRow("Số bản", self.copies)
        self.scope = self._combo("Tất cả", "Trang hiện tại", "Tùy chọn")
        form.addRow("Phạm vi trang", self.scope)
        self.specification = QLineEdit()
        self.specification.setPlaceholderText("Ví dụ 1–3, 7")
        form.addRow(self.specification)
        self.parity = self._combo("Tất cả trang đã chọn", "Trang lẻ", "Trang chẵn")
        form.addRow("Trang in", self.parity)
        self.sides = self._combo("In một mặt", "In hai mặt", "In hai mặt thủ công")
        form.addRow("Số mặt", self.sides)
        self.orientation = self._combo("Dọc", "Ngang")
        form.addRow("Hướng giấy", self.orientation)
        self.flip = self._combo("Cạnh dài", "Cạnh ngắn")
        form.addRow("Lật theo", self.flip)
        self.paper = self._combo()
        for value, (label, _, _) in PAPERS.items():
            self.paper.addItem(label, value)
        form.addRow("Khổ giấy", self.paper)
        self.scale = self._combo("Vừa khổ giấy", "Kích thước thật")
        form.addRow("Tỷ lệ", self.scale)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.message)

        preview_box = QVBoxLayout()
        body.addLayout(preview_box, 6)
        preview_box.addWidget(QLabel("Xem trước"))
        self.preview = PaperPreview()
        preview_box.addWidget(self.preview, 1)
        pagination = QHBoxLayout()
        preview_box.addLayout(pagination)
        pagination.addStretch()
        previous = QPushButton("‹")
        previous.clicked.connect(lambda: self._move_preview(-1))
        pagination.addWidget(previous)
        self.counter = QLabel()
        pagination.addWidget(self.counter)
        following = QPushButton("›")
        following.clicked.connect(lambda: self._move_preview(1))
        pagination.addWidget(following)
        pagination.addStretch()

        footer = QHBoxLayout()
        root.addLayout(footer)
        self.help = QPushButton("Hỗ trợ in  ›")
        self.help.clicked.connect(self._support)
        footer.addWidget(self.help)
        footer.addStretch()
        self.print_current = QPushButton("In trang hiện tại")
        self.print_current.clicked.connect(lambda: self._print([self.current]))
        footer.addWidget(self.print_current)
        cancel = QPushButton("Hủy")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.print_button = QPushButton("In")
        self.print_button.setStyleSheet("background:#175bdf;color:white;padding:7px 22px;")
        self.print_button.clicked.connect(self._submit_selection)
        footer.addWidget(self.print_button)

        self.update_timer = QTimer(self, singleShot=True, interval=140)
        self.update_timer.timeout.connect(self._update_preview)
        for combo in (self.scope, self.parity, self.sides, self.orientation,
                      self.flip, self.paper, self.scale):
            combo.currentIndexChanged.connect(self._schedule_preview)
        self.specification.textChanged.connect(self._schedule_preview)
        self.printers.currentIndexChanged.connect(self._select_printer)

    def _profile(self):
        key = hashlib.sha256(self.printers.currentText().encode()).hexdigest()
        return f"printerProfiles/{key}"

    def _select_printer(self):
        self.mode = None
        name = self.printers.currentText()
        self.driver.setText("Chưa có máy in Windows.")
        self.duplex_supported = False
        self.sides.setEnabled(bool(name) and sys.platform == "win32")
        self.sides.model().item(1).setEnabled(False)
        if sys.platform == "win32" and name:
            try:
                import win32print

                info = printer_info(name)
                self.mode = driver_mode(name)
                self.driver.setText(f"Driver Windows · {info['pDriverName']}")
                port = info["pPortName"]
                duplex = win32print.DeviceCapabilities(name, port, 7) == 1
                self.duplex_supported = duplex
                self.sides.model().item(1).setEnabled(duplex)
                codes = win32print.DeviceCapabilities(name, port, 2)
                labels = win32print.DeviceCapabilities(name, port, 16)
                sizes = win32print.DeviceCapabilities(name, port, 3)
                if codes and labels and sizes:
                    self.paper.clear()
                    for code, label, size in zip(codes, labels, sizes):
                        width, height = size["x"], size["y"]
                        if width > 0 and height > 0:
                            self.paper.addItem(label.rstrip("\x00 ").strip(), (code, width / 10, height / 10))
            except Exception as exc:
                self.driver.setText(f"Không đọc được driver · {exc}")
        self._apply_mode()
        self.settings.beginGroup(self._profile())
        try:
            self._select_paper(self.settings.value("paper", self._paper()[0], type=int))
            for key, widget in (("orientation", self.orientation), ("scale", self.scale),
                                ("sides", self.sides), ("flip", self.flip)):
                widget.setCurrentIndex(self.settings.value(key, widget.currentIndex(), type=int))
        finally:
            self.settings.endGroup()
        if not self.sides.isEnabled() or (self.sides.currentIndex() == 1 and not self.duplex_supported):
            self.sides.setCurrentIndex(0)
        self._update_preview()

    def _paper(self):
        value = self.paper.currentData()
        if isinstance(value, (tuple, list)):
            return value
        _, width, height = PAPERS.get(value, PAPERS[9])
        return value or 9, width, height

    def _select_paper(self, code):
        for index in range(self.paper.count()):
            value = self.paper.itemData(index)
            if (value[0] if isinstance(value, (list, tuple)) else value) == code:
                self.paper.setCurrentIndex(index)
                break

    def _apply_mode(self):
        self.orientation.setCurrentIndex(0)
        self.sides.setCurrentIndex(0)
        self.flip.setCurrentIndex(0)
        self._select_paper(9)
        if self.mode is None:
            return
        self._select_paper(self.mode.PaperSize)
        self.orientation.setCurrentIndex(int(self.mode.Orientation == 2))
        self.sides.setCurrentIndex(int(self.duplex_supported and self.mode.Duplex in (2, 3)))
        self.flip.setCurrentIndex(int(self.mode.Duplex == 3))

    def _duplex(self):
        return 2 + self.flip.currentIndex() if self.duplex_supported and self.sides.currentIndex() == 1 else 1

    def _configured(self):
        return configured_mode(self.printers.currentText(), self.mode, self._paper()[0],
                               self.orientation.currentIndex() == 1, self._duplex(), self.copies.value())

    def _properties(self):
        if self.mode is None:
            QMessageBox.information(self, "Máy in", "Chọn máy in Windows trước.")
            return
        try:
            self._configured()
            if driver_properties(self.printers.currentText(), int(self.winId()), self.mode):
                self._apply_mode()
                self.copies.setValue(max(1, self.mode.Copies))
                self._update_preview()
        except Exception as exc:
            QMessageBox.warning(self, "Thuộc tính máy in", str(exc))

    def _schedule_preview(self, *_):
        self.update_timer.start()

    def _move_preview(self, step):
        self.preview_position = max(0, min(len(self.page_list) - 1, self.preview_position + step))
        self._update_preview()

    def _update_preview(self):
        self.specification.setEnabled(self.scope.currentIndex() == 2)
        self.flip.setEnabled(self._duplex() != 1)
        self.print_current.setEnabled(self.mode is not None)
        try:
            pages = selected_pages(len(self.document), self.current, self.scope.currentIndex(),
                                   self.specification.text(), self.parity.currentIndex())
        except ValueError as exc:
            self.page_list = []
            self.counter.setText("0 / 0")
            self.preview.image = QImage()
            self.preview_page = None
            self.preview.update()
            self.message.setText(str(exc))
            self.print_button.setEnabled(False)
            return
        if pages != self.page_list:
            self.preview_position = 0
        self.page_list = pages
        index = pages[self.preview_position]
        self.counter.setText(f"{self.preview_position + 1} / {len(pages)} · Trang {index + 1}")
        self.print_button.setEnabled(self.mode is not None)
        self.message.clear()
        _, width, height = self._paper()
        self.preview.paper_mm = (height, width) if self.orientation.currentIndex() == 1 else (width, height)
        self.preview.actual_size = self.scale.currentIndex() == 1
        self.preview.margins = (0, 0, 0, 0)
        if self.mode is not None:
            try:
                from windows_print import printable_margins
                self.preview.margins = printable_margins(self.printers.currentText(), self._configured())
            except Exception:
                self.message.setText("Chưa đọc được vùng in của driver. Mép giấy chỉ là ước tính.")
        if self.preview_page != index:
            page = None
            try:
                page = self.document[index]
                self.preview.page_mm = tuple(value * 25.4 / 72 for value in page.get_size())
                bitmap = page.render(scale=min(1.5, 1500 / max(page.get_size())),
                                     draw_annots=True, may_draw_forms=True)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    self.preview.image = QImage(image.tobytes(), image.width, image.height,
                                                image.width * 3, QImage.Format.Format_RGB888).copy()
                finally:
                    bitmap.close()
                self.preview_page = index
            except Exception as exc:
                self.preview.image = QImage()
                self.message.setText(f"Không xem trước được trang {index + 1} · {exc}")
            finally:
                if page is not None:
                    page.close()
        self.preview.update()

    def _save_profile(self):
        self.settings.beginGroup(self._profile())
        try:
            self.settings.setValue("paper", self._paper()[0])
            for key, widget in (("orientation", self.orientation), ("scale", self.scale),
                                ("sides", self.sides), ("flip", self.flip)):
                self.settings.setValue(key, widget.currentIndex())
        finally:
            self.settings.endGroup()

    def _submit_selection(self):
        self._update_preview()
        if self.mode is None or not self.page_list:
            return
        if self.sides.currentIndex() != 2 or len(self.page_list) < 2:
            self._print(self.page_list)
            return
        if self.copies.value() != 1:
            QMessageBox.information(self, "In hai mặt thủ công", "Chọn một bản cho mỗi lượt in thủ công.")
            return
        if QMessageBox.question(
            self, "In hai mặt thủ công",
            "Hãy thử với hai trang trước để biết chiều nạp giấy của máy. Gửi lượt in mặt trước?"
        ) != QMessageBox.StandardButton.Yes:
            return
        pages = self.page_list[:]
        fronts = pages[::2]
        backs = pages[1::2]
        self._print(fronts)
        if self.last_error:
            return
        order, confirmed = QInputDialog.getItem(
            self, "Nạp lại giấy",
            "Đợi in xong. Nếu tài liệu có số trang lẻ, lấy tờ cuối ra trước khi nạp lại. "
            "Nạp giấy theo chiều đã in thử và chọn thứ tự in mặt sau.",
            ["Đảo thứ tự mặt sau", "Giữ thứ tự mặt sau"], 0, False)
        if confirmed:
            self._print(list(reversed(backs)) if order.startswith("Đảo") else backs)

    def _print(self, pages, image_dpi=None):
        if self.mode is None or not pages:
            return
        self.last_error = ""
        name = self.printers.currentText()
        self.last_request = (name, tuple(pages))
        self.last_job = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.last_job = send_pdf(name, self._configured(), self.document, pages,
                                     self.scale.currentIndex() == 1, image_dpi=image_dpi)
        except Exception as exc:
            self.last_job = getattr(exc, "job_id", None)
            page = getattr(exc, "page", None)
            self.last_error = f"Trang {page + 1} · {exc}" if page is not None else str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if self.last_error:
            self.message.setText(self.last_error)
            return
        self._save_profile()
        self.message.setText(f"Đã gửi vào hàng đợi Windows · Lệnh {self.last_job}")

    def _state(self):
        if sys.platform != "win32" or not self.printers.currentText():
            return "Chưa có máy in Windows."
        try:
            import win32print

            name = self.printers.currentText()
            if self.last_request and self.last_request[0] == name and self.last_job:
                try:
                    with printer_handle(name) as handle:
                        job = win32print.GetJob(handle, self.last_job, 1)
                    status = job.get("pStatus")
                    if status:
                        return str(status)
                    for flag, label in ((2, "Hàng đợi báo lỗi"), (32, "Máy in ngoại tuyến"),
                                        (64, "Hết giấy"), (16, "Đang in"), (8, "Đang chờ xử lý")):
                        if job["Status"] & flag:
                            return label
                except Exception:
                    pass
            status = printer_info(name)["Status"]
            for flag, label in ((8, "Kẹt giấy"), (16, "Hết giấy"), (128, "Ngoại tuyến"), (2, "Máy in báo lỗi")):
                if status & flag:
                    return label
        except Exception:
            pass
        return "Chưa xác định được nguyên nhân."

    def _support(self):
        name = self.printers.currentText()
        menu = QMenu(self)
        header = menu.addAction(f"{name or 'Máy in'} · {self._state()}")
        header.setEnabled(False)
        menu.addSeparator()
        queue = menu.addAction("Mở hàng đợi in")
        test = menu.addAction("In trang kiểm tra Windows")
        copy = menu.addAction("Sao chép thông tin lỗi")
        retry = menu.addAction("Thử lại dưới dạng ảnh")
        queue.setEnabled(bool(name) and sys.platform == "win32")
        test.setEnabled(queue.isEnabled())
        retry.setEnabled(self.mode is not None and bool(self.last_request) and self.last_request[0] == name)
        action = menu.exec(self.help.mapToGlobal(self.help.rect().topLeft()))
        if action in (queue, test):
            flag = "/o" if action == queue else "/k"
            if action == test and QMessageBox.question(self, "Trang kiểm tra", "Gửi một trang kiểm tra Windows?") != QMessageBox.StandardButton.Yes:
                return
            try:
                subprocess.Popen(["rundll32.exe", "printui.dll,PrintUIEntry", flag, "/n", name])
            except OSError as exc:
                QMessageBox.warning(self, "Hỗ trợ in", str(exc))
        elif action == copy:
            # Driver errors may embed file paths. Only copy the numeric job reference and status.
            QApplication.clipboard().setText(
                f"Máy in: {name}\n{self.driver.text().split(' · ')[0] if self.mode is None else self.driver.text()}\n"
                f"Khổ giấy: {self.paper.currentText()}\nLệnh Windows: {self.last_job or '—'}\n"
                f"Trạng thái: {'Lỗi gửi lệnh' if self.last_error else self._state()}")
        elif action == retry:
            dpi, accepted = QInputDialog.getItem(self, "Thử lại dưới dạng ảnh", "Độ phân giải (dpi)",
                                                 ["150", "200", "300"], 2, False)
            if accepted and QMessageBox.question(
                self, "Xác nhận in lại", "Kiểm tra lệnh cũ trong hàng đợi để tránh in trùng. Gửi lại các trang của lần in trước?"
            ) == QMessageBox.StandardButton.Yes:
                self._print(self.last_request[1], image_dpi=int(dpi))
