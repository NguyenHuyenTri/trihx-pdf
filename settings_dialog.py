import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError

from PySide6.QtCore import QStandardPaths, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QDialog, QGroupBox, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

from app_update import APP_VERSION, check_for_update, download_installer, launch_installer
from appearance import MODES


class UpdateJob(QThread):
    progress = Signal(int)

    def __init__(self, release, directory, parent):
        super().__init__(parent)
        self.release = release
        self.directory = directory
        self.result = None
        self.error = None

    def run(self):
        try:
            if self.release is None:
                self.result = check_for_update()
            else:
                self.result = download_installer(self.release, self.directory, self.progress.emit,
                                                 self.isInterruptionRequested)
        except HTTPError as exc:
            self.error = f"GitHub trả về lỗi HTTP {exc.code}. Hãy thử lại sau."
            exc.close()
        except (URLError, HTTPException, TimeoutError):
            self.error = "Kết nối đến GitHub bị gián đoạn. Hãy kiểm tra mạng rồi thử lại."
        except Exception as exc:
            self.error = str(exc)


def cache_directory():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "updates"


def clean_old_downloads():
    directory = cache_directory()
    cutoff = time.time() - 24 * 60 * 60
    try:
        for path in directory.glob("trihx-setup-*"):
            if path.suffix in (".part", ".exe") and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


class SettingsDialog(QDialog):
    appearance_changed = Signal(str, str)

    def __init__(self, mode, custom_color, parent=None):
        super().__init__(parent)
        self.setObjectName("readerSettings")
        self.setWindowTitle("Cài đặt TRIHX PDF")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self.theme_mode = mode
        self.custom_color = custom_color
        self.release = None
        self.installer = None
        self.install_started = False
        self.job = None
        self.cancelling = False
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
        self.action = QPushButton("Kiểm tra cập nhật")
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
        if self.installer is not None:
            try:
                launch_installer(self.installer)
            except OSError as exc:
                self.status.setText(f"Windows chưa mở được bộ cài. {exc}")
                return
            self.installer = None
            self.install_started = True
            self.accept()
            return
        checking = self.release is None
        self.status.setText("Đang kiểm tra phiên bản…" if checking else
                            f"Đang tải TRIHX PDF {self.release.version}…")
        self.status.show()
        self.bar.setRange(0, 0 if checking else 100)
        self.bar.setValue(0)
        self.bar.show()
        self.action.hide()
        self.dismiss.setText("Hủy và đóng")
        self.job = UpdateJob(self.release, cache_directory(), self)
        self.job.progress.connect(self.bar.setValue)
        self.job.finished.connect(self._finished)
        self.job.start()

    def _finished(self):
        job = self.job
        self.job = None
        result, error = job.result, job.error
        job.deleteLater()
        if isinstance(result, Path):
            self.installer = result
        if self.cancelling:
            self.reject()
            return
        self.bar.hide()
        self.dismiss.setText("Đóng")
        if error:
            self.status.setText(error)
            self.action.setText("Thử lại")
        elif self.installer:
            self.status.setText("Đã tải và kiểm tra bộ cài. Bấm Cài bản mới để đóng các tab PDF và mở bộ cài Windows.")
            self.action.setText("Cài bản mới")
        elif result is None:
            self.status.setText("Bạn đang dùng phiên bản mới nhất hiện có.")
            self.action.setText("Kiểm tra lại")
        else:
            self.release = result
            size_mb = self.release.size / (1024 * 1024)
            self.status.setText(f"Có phiên bản {self.release.version} cho Windows ({size_mb:.1f} MB).")
            self.action.setText("Tải bản mới")
        self.action.show()

    def reject(self):
        if self.job is not None:
            self.cancelling = True
            self.job.requestInterruption()
            self.dismiss.setEnabled(False)
            self.status.setText("Đang hủy…")
            return
        if self.installer is not None:
            try:
                self.installer.unlink(missing_ok=True)
            except OSError:
                pass
        super().reject()
