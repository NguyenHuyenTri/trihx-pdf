"""Read the icon that Windows actually draws for a file, shortcut or window."""

from pathlib import Path

import win32con
import win32gui
from win32com.shell import shell, shellcon


def mark_pixels(icon):
    if not icon:
        raise AssertionError("Windows did not supply an icon")
    screen = win32gui.GetDC(0)
    dc = win32gui.CreateCompatibleDC(screen)
    bitmap = win32gui.CreateCompatibleBitmap(screen, 32, 32)
    previous = win32gui.SelectObject(dc, bitmap)
    try:
        win32gui.FillRect(dc, (0, 0, 32, 32), win32gui.GetStockObject(win32con.BLACK_BRUSH))
        win32gui.DrawIconEx(dc, 0, 0, icon, 32, 32, 0, 0, win32con.DI_NORMAL)
        # Sample the tile and the T above the optional shortcut arrow.
        pixels = []
        for y in range(4, 23, 2):
            for x in range(5, 28, 2):
                color = win32gui.GetPixel(dc, x, y)
                r, g, b = color & 255, (color >> 8) & 255, (color >> 16) & 255
                pixels.append("r" if r > 160 and max(g, b) < 125 else "w" if min(r, g, b) > 195 else ".")
        return pixels
    finally:
        win32gui.SelectObject(dc, previous)
        win32gui.DeleteObject(bitmap)
        win32gui.DeleteDC(dc)
        win32gui.ReleaseDC(0, screen)


def file_mark(path):
    if not Path(path).is_file():
        raise AssertionError(f"Missing shell item {path}")
    _, info = shell.SHGetFileInfo(str(path), 0, shellcon.SHGFI_ICON | shellcon.SHGFI_LARGEICON)
    icon = info[0]
    try:
        return mark_pixels(icon)
    finally:
        win32gui.DestroyIcon(icon)


def matches_mark(actual, reference):
    return sum(a == b for a, b in zip(actual, reference)) >= 0.90 * len(reference)


def executable_mark(path):
    large, small = win32gui.ExtractIconEx(str(path), 0)
    try:
        return mark_pixels(large[0])
    finally:
        for icon in (*large, *small):
            win32gui.DestroyIcon(icon)


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps([file_mark(path) for path in sys.argv[1:]]))
