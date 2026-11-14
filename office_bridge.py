"""Open originals with the installed desktop Office applications."""
from pathlib import Path
import os
import re
import sys
import subprocess

OFFICE_TYPES = {
    ".docx": ("Word", "Documents", "W", "#2563bb"),
    ".doc": ("Word", "Documents", "W", "#2563bb"),
    ".xlsx": ("Excel", "Workbooks", "X", "#23774a"),
    ".xls": ("Excel", "Workbooks", "X", "#23774a"),
    ".pptx": ("PowerPoint", "Presentations", "P", "#bc4a28"),
    ".ppt": ("PowerPoint", "Presentations", "P", "#bc4a28"),
}
DOCUMENT_TYPES = {".pdf", *OFFICE_TYPES}
FILE_FILTER = "Tài liệu (*.pdf *.docx *.doc *.xlsx *.xls *.pptx *.ppt)"


OFFICE_EXECUTABLES = {
    "Word": "WINWORD.EXE",
    "Excel": "EXCEL.EXE",
    "PowerPoint": "POWERPNT.EXE",
}
_office_sessions = {}


def native_office_program(application):
    import winreg

    executable = OFFICE_EXECUTABLES[application]
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    program = Path(os.path.expandvars(winreg.QueryValueEx(key, "")[0]).strip('"'))
                if program.name.casefold() == executable.casefold() and program.is_file():
                    return program.resolve()
            except OSError:
                continue
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        directory = os.environ.get(variable)
        if directory:
            for version in ("root/Office16", "Office16", "Office15", "Office14"):
                program = Path(directory) / "Microsoft Office" / version / executable
                if program.is_file():
                    return program.resolve()
    raise RuntimeError(f"Không tìm thấy Microsoft {application} bản desktop. Nếu máy chỉ có WPS, "
                       "hãy cài Microsoft Office để mở tài liệu bằng Microsoft Office trong TRIHX.")


def office_process_path(hwnd):
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32process

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process = win32api.OpenProcess(0x1000, False, pid)
    try:
        query = ctypes.windll.kernel32.QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                          ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not query(int(process), 0, buffer, ctypes.byref(length)):
            raise ctypes.WinError()
        return Path(buffer.value).resolve()
    finally:
        process.Close()


def find_office_window(path, program):
    import win32gui

    # Office can collapse whitespace and hide the filename extension.
    def normalize(value):
        return " ".join(value.split()).casefold()

    names = {normalize(path.name), normalize(path.stem)}
    matches = []
    rejected = []

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = normalize(win32gui.GetWindowText(hwnd))
        if any(title == name or title.startswith(tuple(name + sep for sep in
               (" - ", " – ", " — ", " [", " (", " • "))) for name in names):
            try:
                executable = office_process_path(hwnd)
                if os.path.samefile(executable, program):
                    matches.append(hwnd)
                else:
                    rejected.append("Cửa sổ cùng tên thuộc chương trình khác.")
            except Exception as exc:
                rejected.append(f"Không xác minh được tiến trình Office: {exc}")
        return True

    win32gui.EnumWindows(collect, None)
    # A title alone cannot disambiguate documents with the same name.
    if len(matches) > 1:
        raise RuntimeError("Có nhiều cửa sổ Office cùng tên. Hãy đóng các tệp trùng tên rồi thử lại.")
    if not matches and rejected:
        raise RuntimeError(rejected[0])
    return matches[0] if matches else 0


def verify_com_registration(prog_id, program):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\CLSID") as key:
        clsid = winreg.QueryValueEx(key, "")[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as key:
        command = os.path.expandvars(winreg.QueryValueEx(key, "")[0]).strip()
    match = re.match(r'(?:"([^"]+)"|(.+?\.exe)(?:\s|$))', command, re.IGNORECASE)
    if not match:
        raise RuntimeError("Không xác định được chương trình đăng ký tự động hóa Office.")
    registered = Path(match.group(1) or match.group(2)).resolve()
    if registered != program:
        raise RuntimeError("Đăng ký tự động hóa Office đang trỏ tới chương trình khác.")


def verify_office_server(app, program):
    # Application.Path is available before opening a document, even if Word has no active window.
    app_path = Path(str(app.Path)) / program.name
    if os.path.normcase(str(app_path.resolve())) != os.path.normcase(str(program)):
        raise RuntimeError("Đăng ký tự động hóa Office đang trỏ tới chương trình khác.")


def show_office(path: Path, *, printing=False):
    if sys.platform != "win32":
        raise RuntimeError("Cần Windows và Microsoft Office bản desktop.")
    application = OFFICE_TYPES[path.suffix.lower()][0]
    program = native_office_program(application)
    try:
        hwnd = _activate_document(path, program, printing=printing)
        return hwnd, program
    except Exception:
        if printing:
            raise
        subprocess.Popen([str(program), str(path)])
        return 0, program


def _activate_document(path, program, *, printing):
    import win32com.client
    import win32con
    import win32gui
    from pywintypes import com_error

    app_name, collection_name, _, _ = OFFICE_TYPES[path.suffix.lower()]
    prog_id = f"{app_name}.Application"
    try:
        app = win32com.client.GetActiveObject(prog_id)
    except com_error:
        verify_com_registration(prog_id, program)
        app = win32com.client.Dispatch(prog_id)
    verify_office_server(app, program)
    _office_sessions[app_name] = app
    collection = getattr(app, collection_name)
    target = os.path.normcase(str(path))
    document = None
    for entry in collection:
        try:
            if os.path.normcase(str(entry.FullName)) == target:
                document = entry
                break
        except com_error:
            continue

    if document is None:
        prior_security = app.AutomationSecurity
        try:
            app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
            document = collection.Open(str(path))
        finally:
            app.AutomationSecurity = prior_security

    app.Visible = True
    if app_name == "Word":
        document.Activate()
    else:
        document.Windows(1).Activate()

    hwnd = 0
    owners = [app]
    try:
        owners.insert(0, app.ActiveWindow)
    except (AttributeError, com_error):
        pass
    for owner in owners:
        try:
            hwnd = win32gui.GetAncestor(int(owner.Hwnd), 2)
            if hwnd and win32gui.IsWindow(hwnd):
                break
            hwnd = 0
        except (AttributeError, com_error, OSError):
            continue
    if hwnd and not os.path.samefile(office_process_path(hwnd), program):
        raise RuntimeError("Cửa sổ tài liệu không thuộc Microsoft Office đã chọn.")
    if hwnd:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            win32gui.FlashWindow(hwnd, True)
    if printing:
        app.CommandBars.ExecuteMso("PrintPreviewAndPrint")
    return hwnd


class OfficeWindow:
    """Host the Office window in the active document pane."""
    def __init__(self, hwnd):
        import win32con
        import win32gui

        self.hwnd = hwnd
        self.placement = win32gui.GetWindowPlacement(hwnd)
        self.style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        self.original_parent = win32gui.GetAncestor(hwnd, 1)  # GA_PARENT excludes the owner.
        self.identity = self._identity()
        self.host = None

    def _identity(self):
        import win32process

        return win32process.GetWindowThreadProcessId(self.hwnd)

    def _exists(self):
        import win32gui

        return win32gui.IsWindow(self.hwnd) and self._identity() == self.identity

    def dock(self, host, width, height, *, hide_title=False):
        import win32con
        import win32gui

        if not self._exists():
            raise RuntimeError("Cửa sổ Office đã thay đổi hoặc đã đóng.")
        if width <= 0 or height <= 0:
            return
        flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER
        style = (self.style | win32con.WS_CHILD) & ~(win32con.WS_POPUP | win32con.WS_THICKFRAME)
        if hide_title:
            style &= ~win32con.WS_CAPTION
        if self.host != host or win32gui.GetParent(self.hwnd) != host:
            show_command = win32gui.GetWindowPlacement(self.hwnd)[1]
            if win32gui.IsIconic(self.hwnd) or show_command == win32con.SW_SHOWMAXIMIZED:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            if win32gui.GetParent(self.hwnd) != host:
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, style)
                win32gui.SetParent(self.hwnd, host)
                self.host = host
            if win32gui.GetParent(self.hwnd) != host:
                raise RuntimeError("Windows không gắn được cửa sổ Office vào tab.")
            self.host = host
            flags |= win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW
        elif win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE) != style:
            win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, style)
            flags |= win32con.SWP_FRAMECHANGED
        win32gui.SetWindowPos(self.hwnd, 0, 0, 0, width, height, flags)
        if win32gui.GetParent(self.hwnd) != host:
            raise RuntimeError("Office đã tách cửa sổ khỏi vùng tài liệu.")

    def restore(self):
        import win32con
        import win32gui

        if not self._exists():
            return
        if self.host is not None and win32gui.GetParent(self.hwnd) == self.host:
            parent = self.original_parent
            if parent == win32gui.GetDesktopWindow():
                parent = 0
            win32gui.SetParent(self.hwnd, parent or 0)
            self.host = None
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, self.style)
        win32gui.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, win32con.SWP_FRAMECHANGED |
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                              win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        win32gui.SetWindowPlacement(self.hwnd, self.placement)
