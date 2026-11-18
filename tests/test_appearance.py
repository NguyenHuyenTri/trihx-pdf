import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from appearance import DEFAULT_CUSTOM_COLOR, read_appearance, theme_colors
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
        reader.show()
        self.app.processEvents()
        return reader

    def test_menu_changes_visible_chrome_and_remembers_custom_color(self):
        reader = self.reader
        reader.resize(reader.minimumSize())
        self.app.processEvents()
        self.assertTrue(reader.theme_button.isVisibleTo(reader))
        self.assertTrue(reader.menuWidget().rect().contains(reader.theme_button.geometry()))
        self.assertEqual([action.text() for action in reader.theme_button.menu().actions()],
                         ["Sáng", "Tối", "Màu tùy chọn…"])
        self.assertTrue(reader.theme_actions["light"].isChecked())
        reader.theme_actions["dark"].trigger()
        self.assertEqual(self.app.palette().window().color().name(), reader.colors["canvas"])
        self.assertEqual(reader.menuWidget().grab().toImage().pixelColor(2, 4).name(), reader.colors["title"])

        with patch("main.QColorDialog.getColor", return_value=QColor("#d2aa35")):
            reader.theme_actions["custom"].trigger()
        self.assertEqual(reader.menuWidget().grab().toImage().pixelColor(2, 4).name(), "#d2aa35")
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Accent).name(), "#d2aa35")
        reader.close()
        reopened = self.open_reader()
        self.assertTrue(reopened.theme_actions["custom"].isChecked())
        self.assertEqual((reopened.theme_mode, reopened.colors["title"]), ("custom", "#d2aa35"))
        reopened.theme_actions["light"].trigger()
        with patch("main.QColorDialog.getColor", return_value=QColor()) as picker:
            reopened.theme_actions["custom"].trigger()
        self.assertEqual(picker.call_args.args[0].name(), "#d2aa35")
        self.assertTrue(reopened.theme_actions["light"].isChecked())
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
        self.reader.theme_actions["dark"].trigger()
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

    def test_contrast_and_damaged_preferences(self):
        for background, ink in (("#ffffff", "#000000"), ("#ffed00", "#000000"),
                                ("#000000", "#ffffff"), ("#160d67", "#ffffff")):
            with self.subTest(background=background):
                self.assertEqual(theme_colors("custom", background)["title_text"], ink)
        self.reader.settings.setValue("appearance/mode", "custom")
        self.reader.settings.setValue("appearance/customColor", "broken")
        self.assertEqual(read_appearance(self.reader.settings), ("light", DEFAULT_CUSTOM_COLOR))
