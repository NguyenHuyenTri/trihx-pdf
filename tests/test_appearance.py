import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QGroupBox, QToolButton

from appearance import DEFAULT_CUSTOM_COLOR, read_appearance, theme_colors
from app_update import APP_VERSION
from brand_icon import application_icon, draw_mark
from main import PdfReaderWindow
from print_dialog import PaperPreview


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.directory = Path(directory)
        settings_file = str(self.directory / "settings.ini")
        self.enterContext(patch("main.QSettings", side_effect=lambda *args: QSettings(settings_file, QSettings.Format.IniFormat)))
        self.reader = self.open_reader()

    def open_reader(self):
        reader = PdfReaderWindow()
        self.addCleanup(reader.close)
        self.addCleanup(lambda: reader.settings_dialog and reader.settings_dialog.reject())
        reader.show()
        self.app.processEvents()
        return reader

    def test_settings_dialog_changes_visible_chrome_and_remembers_custom_color(self):
        reader = self.reader
        reader.resize(reader.minimumSize())
        self.app.processEvents()
        self.assertEqual(reader.settings_button.text(), "Cài đặt")
        self.assertTrue(reader.settings_button.isVisibleTo(reader))
        self.assertTrue(reader.menuWidget().rect().contains(reader.settings_button.geometry()))
        self.assertIsNone(reader.settings_button.menu())
        self.assertIsNone(reader.statusBar().findChild(QToolButton, "updateButton"))
        reader.settings_button.click()
        dialog = reader.settings_dialog
        self.assertFalse(dialog.isModal())
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.windowTitle(), "Cài đặt TRIHX PDF")
        self.assertEqual([box.title() for box in dialog.findChildren(QGroupBox)], ["Giao diện", "Cập nhật"])
        self.assertIn(APP_VERSION, dialog.version_label.text())
        self.assertEqual(dialog.action.text(), "Cập nhật ngay")
        self.assertTrue(dialog.theme_buttons["light"].isChecked())
        dialog.theme_buttons["dark"].click()
        self.assertEqual(self.app.palette().window().color().name(), reader.colors["canvas"])
        self.assertEqual(reader.menuWidget().grab().toImage().pixelColor(2, 4).name(), reader.colors["title"])

        with patch("settings_dialog.QColorDialog.getColor", return_value=QColor("#d2aa35")):
            dialog.theme_buttons["custom"].click()
        self.assertEqual(reader.menuWidget().grab().toImage().pixelColor(2, 4).name(), "#d2aa35")
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Accent).name(), "#d2aa35")
        dialog.dismiss.click()
        self.assertFalse(dialog.isVisible())
        self.assertTrue(reader.isVisible())
        reader.close()
        reopened = self.open_reader()
        reopened.settings_button.click()
        dialog = reopened.settings_dialog
        self.assertTrue(dialog.theme_buttons["custom"].isChecked())
        self.assertEqual((reopened.theme_mode, reopened.colors["title"]), ("custom", "#d2aa35"))
        dialog.theme_buttons["light"].click()
        with patch("settings_dialog.QColorDialog.getColor", return_value=QColor()) as picker:
            dialog.theme_buttons["custom"].click()
        self.assertEqual(picker.call_args.args[0].name(), "#d2aa35")
        self.assertTrue(dialog.theme_buttons["light"].isChecked())
        self.assertEqual(read_appearance(reopened.settings), ("light", "#d2aa35"))

    def test_open_pdf_and_print_paper_keep_their_colors(self):
        path = self.directory / "color.pdf"
        image = Image.new("RGB", (140, 190), "white")
        ImageDraw.Draw(image).rectangle((40, 45, 100, 145), fill="#bb2636")
        image.save(path, resolution=72.0)
        self.reader.open_file(path)
        self.app.processEvents()
        page = self.reader.page_labels[0]
        paper = page.grab().toImage()
        red = paper.pixelColor(paper.width() // 2, paper.height() // 2)
        self.assertGreater(red.red(), 2 * red.green())
        self.reader.settings_button.click()
        self.reader.settings_dialog.theme_buttons["dark"].click()
        self.reader.settings_dialog.dismiss.click()
        self.assertIs(self.reader.page_labels[0], page)
        self.assertTrue(self.reader.file_path.samefile(path))
        dark_paper = page.grab().toImage()
        self.assertEqual(dark_paper.pixelColor(paper.width() // 2, paper.height() // 2), red)
        self.assertEqual(dark_paper.pixelColor(10, 10).name(), "#ffffff")

        preview = PaperPreview()
        preview.resize(380, 380)
        viewed = preview.grab().toImage()
        self.assertEqual(viewed.pixelColor(1, 1).name(), self.reader.colors["canvas"])
        self.assertEqual(viewed.pixelColor(viewed.width() // 2, viewed.height() // 2).name(), "#ffffff")

    def test_reader_and_tab_bar_share_the_application_mark(self):
        reader = self.reader
        artwork = draw_mark(32)
        self.assertEqual(artwork.pixelColor(5, 17).name(), "#d9242d")
        self.assertEqual(artwork.pixelColor(26, 17).name(), "#d9242d")
        self.assertTrue(any(artwork.pixelColor(x, 17).name() == "#ffffff" for x in range(10, 22)))
        self.assertEqual(artwork.pixelColor(0, 0).alpha(), 0)
        frame = (QSize(32, 32), QIcon.Mode.Normal, QIcon.State.Off)
        mark = application_icon().pixmap(*frame).toImage()
        self.assertEqual(mark, self.app.windowIcon().pixmap(*frame).toImage())
        self.assertEqual(mark, reader.windowIcon().pixmap(*frame).toImage())
        reader.settings_button.click()
        reader.settings_dialog.theme_buttons["dark"].click()
        self.assertEqual(mark, reader.app_home_button.icon().pixmap(*frame).toImage())

    def test_contrast_and_damaged_preferences(self):
        for background, ink in (("#ffffff", "#000000"), ("#ffed00", "#000000"),
                                ("#000000", "#ffffff"), ("#160d67", "#ffffff")):
            with self.subTest(background=background):
                self.assertEqual(theme_colors("custom", background)["title_text"], ink)
        self.reader.settings.setValue("appearance/mode", "custom")
        self.reader.settings.setValue("appearance/customColor", "broken")
        self.assertEqual(read_appearance(self.reader.settings), ("light", DEFAULT_CUSTOM_COLOR))
