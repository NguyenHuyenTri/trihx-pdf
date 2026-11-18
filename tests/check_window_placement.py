"""Check the installed reader on a real Windows desktop during the installer test."""

import ctypes
import json
import sys
import time
from pathlib import Path

import win32api
import win32con
import win32gui
from PySide6.QtCore import QSettings


def wait_for(check, description):
    deadline = time.monotonic() + 15
    while not check():
        if time.monotonic() >= deadline:
            raise AssertionError(description)
        time.sleep(0.1)


def check_window(hwnd, document):
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    if document:
        settings = QSettings("TRIHX", "HX PDF")

        def document_opened():
            settings.sync()
            recent = json.loads(settings.value("recentFilesJson", "[]"))
            return any(Path(entry["path"]) == Path(document) for entry in recent)

        wait_for(document_opened, "The PDF did not open through the installed file association")

    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    work_area = win32api.GetMonitorInfo(monitor)["Work"]
    state = win32gui.GetWindowPlacement(hwnd)[1]
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    client = (*win32gui.ClientToScreen(hwnd, (left, top)), *win32gui.ClientToScreen(hwnd, (right, bottom)))
    print(f"{document or 'Start menu'}: showCmd={state}, client={client}, work area={work_area}", flush=True)
    if state != win32con.SW_SHOWMAXIMIZED or any(abs(a - b) > 1 for a, b in zip(client, work_area)):
        raise AssertionError("The reader must start maximized in the monitor work area")

    # Close the first launch in the restored state. The next launch must maximize again.
    if not document:
        win32gui.PostMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
        wait_for(lambda: win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWNORMAL,
                 "The maximized reader did not restore")
        _, _, width, height = win32gui.GetClientRect(hwnd)
        if width >= work_area[2] - work_area[0] and height >= work_area[3] - work_area[1]:
            raise AssertionError("Restoring should provide a smaller window")


if __name__ == "__main__":
    check_window(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "")
