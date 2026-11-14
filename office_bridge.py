"""Open originals with the installed desktop Office applications."""
from pathlib import Path
import os
import sys

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


def show_office(path: Path, *, printing=False):
    if sys.platform != "win32":
        raise RuntimeError("Cần Windows và Microsoft Office bản desktop.")
    import win32com.client
    from pywintypes import com_error

    app_name, collection_name, _, _ = OFFICE_TYPES[path.suffix.lower()]
    prog_id = f"{app_name}.Application"
    try:
        app = win32com.client.GetActiveObject(prog_id)
    except com_error:
        app = win32com.client.Dispatch(prog_id)
    collection = getattr(app, collection_name)
    target = os.path.normcase(str(path))
    document = next((entry for entry in collection
                     if os.path.normcase(str(entry.FullName)) == target), None)
    if document is None:
        prior_security = app.AutomationSecurity
        try:
            app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
            document = collection.Open(str(path))
        finally:
            app.AutomationSecurity = prior_security
    app.Visible = True
    if app_name == "Excel":
        document.Windows(1).Activate()
    elif app_name == "PowerPoint":
        document.Windows(1).Activate()
    else:
        document.Activate()
    hwnd = 0
    try:
        import win32con
        import win32gui

        window = document.Windows(1) if app_name != "PowerPoint" else app.ActiveWindow
        hwnd = int(window.Hwnd)
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    if printing:
        app.CommandBars.ExecuteMso("PrintPreviewAndPrint")
    return hwnd


class OfficeWindow:
    """Temporarily align a separate Office window with the document area."""
    def __init__(self, hwnd):
        import win32con
        import win32gui

        self.hwnd = hwnd
        self.placement = win32gui.GetWindowPlacement(hwnd)
        self.style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        self.identity = self._identity()

    def _identity(self):
        import win32process

        return win32process.GetWindowThreadProcessId(self.hwnd)

    def move(self, x, y, width, height, *, hide_title=False):
        import win32con
        import win32gui

        if not win32gui.IsWindow(self.hwnd) or self._identity() != self.identity:
            return
        if win32gui.IsIconic(self.hwnd) or win32gui.IsZoomed(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        style = self.style & ~win32con.WS_CAPTION if hide_title else self.style
        if win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE) != style:
            win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, style)
            flags |= win32con.SWP_FRAMECHANGED
        win32gui.SetWindowPos(self.hwnd, 0, x, y, width, height, flags)

    def restore(self):
        import win32con
        import win32gui

        if win32gui.IsWindow(self.hwnd) and self._identity() == self.identity:
            win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, self.style)
            win32gui.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, win32con.SWP_FRAMECHANGED |
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                                  win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
            win32gui.SetWindowPlacement(self.hwnd, self.placement)
