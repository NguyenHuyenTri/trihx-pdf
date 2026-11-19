import hashlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.error import URLError

from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app_update import READER_NAME, Release, stage_update
from main import PdfReaderWindow


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch("settings_dialog.update_directory", return_value=self.directory))
        self.check = self.enterContext(patch("settings_dialog.check_for_update"))
        self.data = b"reader fixture"
        self.enterContext(patch("app_update.open_url", side_effect=lambda *args: io.BytesIO(self.data)))
        self.release = Release("1.0.0", len(self.data), hashlib.sha256(self.data).hexdigest())
        self.reader = PdfReaderWindow()
        self.addCleanup(self.reader.close)
        self.reader.show()
        self.reader.settings_button.click()
        self.dialog = self.reader.settings_dialog
        self.assertFalse(self.dialog.isModal())
        self.assertEqual(self.dialog.action.text(), "Cập nhật ngay")
        self.check.assert_not_called()

    def wait_for_job(self):
        deadline = time.monotonic() + 10
        while self.dialog.job is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.dialog.job)

    def test_current_and_offline_retry(self):
        self.check.side_effect = [URLError("offline"), None]
        self.dialog.action.click()
        self.wait_for_job()
        self.assertEqual(self.dialog.action.text(), "Thử lại")
        self.dialog.action.click()
        self.wait_for_job()
        self.assertIn("mới nhất", self.dialog.status.text())

    def test_keep_reading_and_reopen_settings_during_update(self):
        self.check.return_value = self.release
        path = self.directory / "Báo cáo.pdf"
        Image.new("RGB", (120, 150), "white").save(path)
        self.reader.open_file(path)
        page = self.reader.page_labels[0]
        started, resume = Event(), Event()

        def paused_download(*args):
            started.set()
            if not resume.wait(10):
                raise RuntimeError("Test timed out waiting for the reader")
            return stage_update(*args)

        with patch("settings_dialog.stage_update", side_effect=paused_download):
            self.dialog.action.click()
            try:
                self.assertTrue(started.wait(5))
                self.dialog.dismiss.click()
                self.assertFalse(self.dialog.isVisible())
                self.assertIs(self.reader.page_labels[0], page)
                self.assertTrue(self.reader.file_path.samefile(path))
                self.reader.settings_button.click()
                self.assertIs(self.reader.settings_dialog, self.dialog)
                self.assertIsNotNone(self.dialog.job)
                self.dialog.reject()
            finally:
                resume.set()
                self.wait_for_job()
        self.assertTrue(self.reader.isVisible())
        self.assertIs(self.reader.page_labels[0], page)
        self.assertEqual((self.directory / "1.0.0" / READER_NAME).read_bytes(), self.data)
        self.reader.settings_button.click()
        self.assertIn("1.0.0 đã sẵn sàng", self.dialog.status.text())
        self.check.assert_called_once()

    def test_damaged_payload_can_be_retried(self):
        self.check.return_value = self.release
        with patch("app_update.open_url", return_value=io.BytesIO(b"broken")):
            self.dialog.action.click()
            self.wait_for_job()
        self.assertEqual(self.dialog.action.text(), "Thử lại")
        self.assertFalse((self.directory / "1.0.0" / READER_NAME).exists())
        self.dialog.action.click()
        self.wait_for_job()
        self.assertTrue((self.directory / "1.0.0" / READER_NAME).is_file())
