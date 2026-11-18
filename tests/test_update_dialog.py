import hashlib
import io
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app_update import Release
from update_dialog import UpdateDialog


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        stack = self.enterContext(ExitStack())
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch("update_dialog.cache_directory", return_value=directory))
        self.check = stack.enter_context(patch("update_dialog.check_for_update"))
        self.launch = stack.enter_context(patch("update_dialog.launch_installer"))
        self.data = b"installer fixture"
        stack.enter_context(patch("app_update.open_url", side_effect=lambda *args: io.BytesIO(self.data)))
        self.release = Release("1.0.0", len(self.data), hashlib.sha256(self.data).hexdigest())

    def open_dialog(self):
        self.dialog = UpdateDialog(None)
        self.dialog.show()
        self.addCleanup(self.dialog.close)
        self.wait_for_job()

    def wait_for_job(self):
        deadline = time.monotonic() + 10
        while self.dialog.job is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.dialog.job)

    def test_current_and_offline_retry(self):
        self.check.side_effect = [URLError("offline"), None]
        self.open_dialog()
        self.assertEqual(self.dialog.action.text(), "Thử lại")
        self.dialog.action.click()
        self.wait_for_job()
        self.assertTrue(self.dialog.action.isHidden())
        self.assertIn("mới nhất", self.dialog.status.text())
        self.launch.assert_not_called()

    def test_download_verify_then_explicit_install(self):
        self.check.return_value = self.release
        self.open_dialog()
        self.assertEqual(self.dialog.action.text(), "Tải bản mới")
        self.dialog.action.click()
        self.wait_for_job()
        installer = self.dialog.installer
        self.assertEqual(installer.read_bytes(), self.data)
        self.assertEqual(self.dialog.action.text(), "Cài đặt")
        self.launch.assert_not_called()
        self.launch.side_effect = [OSError("busy"), None]
        self.dialog.action.click()
        self.assertTrue(self.dialog.isVisible())
        self.dialog.action.click()
        self.launch.assert_called_with(installer)
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_can_dismiss_downloaded_update_and_keep_reading(self):
        self.check.return_value = self.release
        self.open_dialog()
        self.dialog.action.click()
        self.wait_for_job()
        installer = self.dialog.installer
        self.dialog.dismiss.click()
        self.assertFalse(installer.exists())
        self.launch.assert_not_called()
