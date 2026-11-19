"""The TRIHX PDF mark used by the reader, Windows launcher and setup."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap


def draw_mark(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    with QPainter(image) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d9242d"))
        painter.drawRoundedRect(QRectF(1, 1, 22, 22), 4, 4)
        # Define both strokes on the same grid so the mark also renders without system fonts.
        painter.fillRect(QRectF(6.3, 5.5, 11.4, 2.6), Qt.GlobalColor.white)
        painter.fillRect(QRectF(10.5, 7.5, 3, 11), Qt.GlobalColor.white)
    return image


def application_icon():
    if getattr(sys, "frozen", False):
        return QIcon(str(Path(__file__).with_name("app_icon.ico")))
    return QIcon(QPixmap.fromImage(draw_mark(256)))


def export_windows_icon(path):
    from io import BytesIO

    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication([])
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not draw_mark(512).save(buffer, "PNG"):
        raise RuntimeError("Could not render the TRIHX PDF icon")
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = (16, 20, 22, 24, 32, 40, 48, 64, 96, 128, 256)
    with Image.open(BytesIO(bytes(buffer.data()))) as master:
        master.convert("RGBA").save(path, format="ICO", sizes=[(n, n) for n in sizes])


if __name__ == "__main__":
    export_windows_icon(Path(sys.argv[1]))
