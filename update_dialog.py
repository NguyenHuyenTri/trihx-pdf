import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError

from PySide6.QtCore import QStandardPaths, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app_update import APP_VERSION, check_for_update, download_installer, launch_installer


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


class UpdateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Cập nhật TRIHX PDF")
        self.setMinimumWidth(380)
        self.release = None
        self.installer = None
        self.job = None
        self.cancelling = False
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.action = QPushButton()
        self.action.clicked.connect(self._next)
        self.dismiss = QPushButton("Hủy")
        self.dismiss.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.dismiss)
        buttons.addWidget(self.action)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Phiên bản đang dùng  {APP_VERSION}"))
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addLayout(buttons)
        self._next()

    def _next(self):
        if self.installer is not None:
            try:
                launch_installer(self.installer)
            except OSError as exc:
                self.status.setText(f"Windows chưa mở được bộ cài. {exc}")
                return
            self.installer = None
            self.accept()
            return
        checking = self.release is None
        self.status.setText("Đang kiểm tra phiên bản…" if checking else
                            f"Đang tải TRIHX PDF {self.release.version}…")
        self.bar.setRange(0, 0 if checking else 100)
        self.bar.setValue(0)
        self.bar.show()
        self.action.hide()
        self.dismiss.setText("Hủy")
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
            self.status.setText("Đã tải và kiểm tra bộ cài. Bấm Cài đặt để đóng các tab PDF và mở bộ cài Windows.")
            self.action.setText("Cài đặt")
        elif result is None:
            self.status.setText("Bạn đang dùng phiên bản mới nhất hiện có.")
            return
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
