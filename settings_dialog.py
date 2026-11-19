from http.client import HTTPException
from pathlib import Path
from time import time
from urllib.error import HTTPError, URLError

from PySide6.QtCore import QStandardPaths, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QDialog, QGroupBox, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

from app_update import APP_VERSION, check_for_update, stage_update, update_directory
from appearance import MODES


def clean_legacy_downloads():
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "updates"
    cutoff = time() - 86400
    for path in directory.glob("trihx-setup-*"):
        try:
            if path.suffix in (".part", ".exe") and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass


class UpdateJob(QThread):
    progress = Signal(int)
    downloading = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.error = None

    def run(self):
        try:
            directory = update_directory()
            release = check_for_update()
            if release is not None and not self.isInterruptionRequested():
                self.downloading.emit(release.version)
                stage_update(release, directory, self.progress.emit, self.isInterruptionRequested)
                self.result = release.version
        except HTTPError as exc:
            self.error = f"GitHub trả về lỗi HTTP {exc.code}. Hãy thử lại sau."
            exc.close()
        except (URLError, HTTPException, TimeoutError):
            self.error = "Kết nối đến GitHub bị gián đoạn. Hãy kiểm tra mạng rồi thử lại."
        except PermissionError:
            self.error = "Windows chưa cho ghi vào thư mục TRIHX PDF. Kiểm tra quyền ghi rồi thử lại."
        except Exception as exc:
            self.error = str(exc)


class SettingsDialog(QDialog):
    appearance_changed = Signal(str, str)
    update_finished = Signal(str)

    def __init__(self, mode, custom_color, parent=None):
        super().__init__(parent)
        self.setObjectName("readerSettings")
        self.setWindowTitle("Cài đặt TRIHX PDF")
        self.setMinimumWidth(440)
        self.theme_mode = mode
        self.custom_color = custom_color
        self.job = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        appearance = QGroupBox("Giao diện")
        choices = QHBoxLayout(appearance)
        choices.setContentsMargins(14, 14, 14, 12)
        choices.setSpacing(16)
        group = QButtonGroup(self)
        self.theme_buttons = {}
        for key, label in MODES.items():
            button = QRadioButton(label)
            button.setProperty("mode", key)
            group.addButton(button)
            button.setChecked(key == mode)
            choices.addWidget(button)
            self.theme_buttons[key] = button
        choices.addStretch()
        group.buttonClicked.connect(self._choose_theme)
        layout.addWidget(appearance)

        updates = QGroupBox("Cập nhật")
        panel = QVBoxLayout(updates)
        panel.setContentsMargins(14, 14, 14, 12)
        version_row = QHBoxLayout()
        self.version_label = QLabel(f"Phiên bản đang dùng   {APP_VERSION}")
        version_row.addWidget(self.version_label)
        version_row.addStretch()
        self.action = QPushButton("Cập nhật ngay")
        self.action.setAutoDefault(False)
        self.action.clicked.connect(self._next)
        version_row.addWidget(self.action)
        panel.addLayout(version_row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        panel.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        panel.addWidget(self.bar)
        layout.addWidget(updates)

        self.dismiss = QPushButton("Đóng")
        self.dismiss.clicked.connect(self.reject)
        layout.addWidget(self.dismiss, alignment=Qt.AlignmentFlag.AlignRight)

    def _choose_theme(self, button):
        mode = button.property("mode")
        if mode == "custom":
            color = QColorDialog.getColor(QColor(self.custom_color), self, "Chọn màu giao diện",
                                          QColorDialog.ColorDialogOption.DontUseNativeDialog)
            if not color.isValid():
                self.theme_buttons[self.theme_mode].setChecked(True)
                return
            self.custom_color = color.name()
        self.theme_mode = mode
        self.appearance_changed.emit(mode, self.custom_color)

    def _next(self):
        if self.job is not None:
            return
        self.status.setText("Đang kiểm tra phiên bản…")
        self.status.show()
        self.bar.setRange(0, 0)
        self.bar.setValue(0)
        self.bar.show()
        self.action.hide()
        self.dismiss.setText("Tiếp tục đọc")
        self.job = UpdateJob(self)
        self.job.downloading.connect(self._downloading)
        self.job.progress.connect(self.bar.setValue)
        self.job.finished.connect(self._finished)
        self.job.start()

    def _downloading(self, version):
        self.status.setText(f"Đang tải TRIHX PDF {version}. Bạn có thể tiếp tục đọc PDF.")
        self.bar.setRange(0, 100)

    def _finished(self):
        job = self.job
        self.job = None
        result, error = job.result, job.error
        job.deleteLater()
        self.bar.hide()
        self.dismiss.setText("Đóng")
        if error:
            self.status.setText(error)
            self.action.setText("Thử lại")
        elif result:
            self.status.setText(f"Bản {result} đã sẵn sàng. Lần mở TRIHX PDF tiếp theo sẽ dùng bản mới.")
            self.action.setText("Kiểm tra lại")
        else:
            self.status.setText("Bạn đang dùng phiên bản mới nhất hiện có.")
            self.action.setText("Kiểm tra lại")
        self.action.show()
        self.update_finished.emit(self.status.text())
