"""Exercise the updater with two real packaged readers and a local release fixture."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import pywintypes
import win32api
import win32con
import win32gui
import win32process
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from win32com.shell import shell, shellcon

# A supplied checkout runs the updater exactly as shipped in the older release.
project = Path(__file__).resolve().parents[1]
sys.path.insert(0, sys.argv[4] if len(sys.argv) > 4 else str(project))
from app_update import APP_VERSION, ASSET_NAME, LATEST_URL, READER_NAME, VERSIONS_DIR, Release
from appearance import DEFAULT_CUSTOM_COLOR
from settings_dialog import SettingsDialog
from windows_icon import executable_mark, file_mark, mark_pixels, matches_mark


def reader_window(expected):
    matches = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "TRIHX PDF":
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                flags = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
                handle = win32api.OpenProcess(flags, False, pid)
                try:
                    if Path(win32process.GetModuleFileNameEx(handle, 0)) == expected:
                        matches.append(hwnd)
                finally:
                    handle.Close()
            except pywintypes.error:
                pass
        return True

    win32gui.EnumWindows(visit, None)
    return next(iter(matches), None)


def wait_until(check, description):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        QApplication.processEvents()
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(description)


def wait_for_pdf(path):
    settings = QSettings("TRIHX", "HX PDF")
    expected = path.resolve()
    recent = []

    def opened():
        settings.sync()
        recent[:] = [item["path"] for item in json.loads(settings.value("recentFilesJson", "[]"))]
        return any(Path(item).resolve() == expected for item in recent)

    try:
        wait_until(opened, "The requested PDF did not open")
    except AssertionError as exc:
        raise AssertionError(f"Expected {str(expected)!a}, recent paths {recent!a}") from exc


def check_update(root, payload, next_version):
    app = QApplication([])
    versions = root / VERSIONS_DIR
    old_exe = versions / APP_VERSION / READER_NAME
    new_exe = versions / next_version / READER_NAME
    with payload.open("rb") as data:
        digest = hashlib.file_digest(data, "sha256").hexdigest()
    release = Release(next_version, payload.stat().st_size, digest)
    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, 0, 0)) / "TRIHX PDF.lnk"
    programs = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, 0, 0))
    links = (desktop, programs / "TRIHX PDF" / "TRIHX PDF.lnk")
    check_legacy_logo = len(sys.argv) > 4
    if check_legacy_logo:
        from PyInstaller.archive.readers import CArchiveReader

        archive = CArchiveReader(str(payload))
        launcher_entry = next(name for name in archive.toc if PureWindowsPath(name) == PureWindowsPath("launcher", READER_NAME))
        updated_launcher = archive.extract(launcher_entry)
        reference = file_mark(payload)
        assert "w" in reference and reference.count("r") > len(reference) // 2
        assert matches_mark(file_mark(project / "dist" / "TRIHX Office Setup.exe"), reference)
        for item in (root / READER_NAME, *links):
            assert not matches_mark(file_mark(item), reference), f"Expected the old icon on {item}"
    metadata = dict(tag_name="v" + next_version, draft=False, prerelease=False,
                    assets=[dict(name=ASSET_NAME, state="uploaded", size=release.size, digest="sha256:" + digest)])

    def release_response(url, accept):
        if url == LATEST_URL:
            return io.BytesIO(json.dumps(metadata).encode())
        if url == release.url:
            return payload.open("rb")
        raise AssertionError(url)

    with tempfile.TemporaryDirectory() as tmp:
        before, after = (Path(tmp) / name for name in ("Tài liệu đang đọc.pdf", "Sau cập nhật.pdf"))
        for pdf in (before, after):
            Image.new("RGB", (100, 150), "white").save(pdf)
        try:
            subprocess.run([root / READER_NAME, before], check=True, timeout=20)
            original = wait_until(lambda: reader_window(old_exe), "Original reader did not start")
            wait_for_pdf(before)
            dialog = SettingsDialog("light", DEFAULT_CUSTOM_COLOR)
            with patch("settings_dialog.update_directory", return_value=versions), \
                    patch("app_update.open_url", side_effect=release_response):
                dialog.show()
                dialog.action.click()
                dialog.reject()
                wait_until(lambda: dialog.job is None, "Background update did not finish")
            assert next_version in dialog.status.text(), dialog.status.text()
            assert reader_window(old_exe) == original
            shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_CLASSNAME, lpClass="HXPDF.Document",
                                 lpVerb="open", lpFile=str(after), nShow=1)
            updated = wait_until(lambda: reader_window(new_exe), "Opening the next PDF did not use the staged version")
            wait_for_pdf(after)
            assert win32gui.IsWindowVisible(original)
            if check_legacy_logo:
                stable = root / READER_NAME
                assert stable.read_bytes() == updated_launcher, "The registered installation still contains the old launcher binary"
                assert matches_mark(executable_mark(stable), reference), "The launcher has a different embedded icon"
                window_icon = win32gui.SendMessage(updated, win32con.WM_GETICON, win32con.ICON_BIG, 0)
                assert matches_mark(mark_pixels(window_icon), reference), "The open reader has a different icon"
                import pythoncom

                for shortcut in links:
                    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
                    link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(shortcut))
                    assert Path(link.GetPath(0)[0]) == stable, f"Shortcut target changed on {shortcut}"
                    icon, index = link.GetIconLocation()
                    assert (Path(icon), index) == (new_exe, 0), f"Unexpected shortcut icon {icon!r}, {index} on {shortcut}"

                # Query the existing shortcuts as a new Shell client after the notification.
                # The process that sampled the old executable retains a private icon list.
                def updated_shortcuts():
                    output = subprocess.check_output([sys.executable, project / "tests" / "windows_icon.py", *links], text=True)
                    return all(matches_mark(mark, reference) for mark in json.loads(output))

                wait_until(updated_shortcuts, "Windows still shows a different icon for the existing Desktop or Start link")
                print("Verified the new mark on the existing Desktop and Start links, launcher, setup and reader window.")
            key_name = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TRIHX.Office.Windows_is1"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
                assert winreg.QueryValueEx(key, "DisplayVersion")[0] == next_version
            print(f"Open PDF stayed in {APP_VERSION}; the next PDF opened in {next_version}.")
        finally:
            for exe in (new_exe, old_exe):
                hwnd = reader_window(exe)
                if hwnd:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    wait_until(lambda: not win32gui.IsWindow(hwnd), "Packaged reader did not close")


if __name__ == "__main__":
    check_update(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
