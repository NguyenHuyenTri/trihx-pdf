"""Windows driver integration shared by both PDF print modes."""
from contextlib import contextmanager
import ctypes


@contextmanager
def printer_handle(name):
    import win32print

    handle = win32print.OpenPrinter(name)
    try:
        yield handle
    finally:
        win32print.ClosePrinter(handle)


def printer_info(name):
    import win32print

    with printer_handle(name) as handle:
        return win32print.GetPrinter(handle, 2)


def driver_mode(name):
    import pywintypes
    import win32con
    import win32print

    with printer_handle(name) as handle:
        mode = win32print.GetPrinter(handle, 2)["pDevMode"]
        if mode is None:
            mode = pywintypes.DEVMODEType()
            extra = win32print.DocumentProperties(0, handle, name, None, None, 0) - mode.Size
            mode = pywintypes.DEVMODEType(max(0, extra))
            result = win32print.DocumentProperties(0, handle, name, mode, None, win32con.DM_OUT_BUFFER)
            if result != 1:
                raise RuntimeError("Không lấy được cấu hình máy in.")
        return mode


def driver_properties(name, hwnd, mode):
    import win32con
    import win32print

    flags = win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER | win32con.DM_PROMPT
    with printer_handle(name) as handle:
        return win32print.DocumentProperties(hwnd, handle, name, mode, mode, flags) == 1


def configured_mode(name, mode, paper, landscape, duplex, copies):
    import win32con
    import win32print

    mode.Fields |= (win32con.DM_PAPERSIZE | win32con.DM_ORIENTATION |
                    win32con.DM_DUPLEX | win32con.DM_COPIES)
    mode.Fields &= ~(win32con.DM_PAPERWIDTH | win32con.DM_PAPERLENGTH)
    mode.PaperSize = paper
    mode.Orientation = 2 if landscape else 1
    mode.Duplex = duplex
    mode.Copies = copies
    with printer_handle(name) as handle:
        flags = win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER
        if win32print.DocumentProperties(0, handle, name, mode, mode, flags) != 1:
            raise RuntimeError("Driver từ chối cấu hình in.")
    return mode


class PrintJobError(RuntimeError):
    def __init__(self, message, page=None, job_id=None):
        super().__init__(message)
        self.page = page
        self.job_id = job_id


def send_pdf(name, mode, document, pages, actual_size, *, image_dpi=None):
    """Return the Windows job ID after submitting the last page."""
    import win32gui
    import win32print
    import pypdfium2.raw as raw

    dc = None
    job_id = None
    index = None
    try:
        dc = win32gui.CreateDC("WINSPOOL", name, mode)
        width, height = win32print.GetDeviceCaps(dc, 8), win32print.GetDeviceCaps(dc, 10)
        dpi_x, dpi_y = win32print.GetDeviceCaps(dc, 88), win32print.GetDeviceCaps(dc, 90)
        if min(width, height, dpi_x, dpi_y) <= 0:
            raise RuntimeError("Driver không cung cấp kích thước vùng in.")
        if image_dpi is None:
            render = getattr(raw, "FPDF_RenderPage", None)
            if render is None:
                # The Windows wheel exports this function but its generated binding omits it.
                render = raw._libs["pdfium"]["FPDF_RenderPage"]
                render.argtypes = [ctypes.c_void_p, raw.FPDF_PAGE, *([ctypes.c_int] * 6)]
                render.restype = None
        job_id = win32print.StartDoc(dc, ("TRIHX Office", None, None, 0))
        if job_id <= 0:
            raise RuntimeError("Windows từ chối tạo lệnh in.")
        for index in pages:
            page = document[index]
            try:
                points_w, points_h = page.get_size()
                size_w = points_w * dpi_x / 72
                size_h = points_h * dpi_y / 72
                factor = 1 if actual_size else min(width / size_w, height / size_h)
                w, h = max(1, round(size_w * factor)), max(1, round(size_h * factor))
                x, y = (width - w) // 2, (height - h) // 2
                win32print.StartPage(dc)
                hdc = dc
                if image_dpi is None:
                    render(int(hdc), page.raw, x, y, w, h, 0,
                                        raw.FPDF_ANNOT | raw.FPDF_PRINTING)
                    if document.formenv is not None:
                        # The bitmap form API draws separately from the HDC renderer.
                        draw_form_fields(raw, int(hdc), document, page, x, y, w, h)
                else:
                    from PIL import ImageWin

                    bitmap = page.render(scale=image_dpi / 72, draw_annots=True,
                                         may_draw_forms=True)
                    try:
                        ImageWin.Dib(bitmap.to_pil().convert("RGB")).draw(int(hdc), (x, y, x + w, y + h))
                    finally:
                        bitmap.close()
                win32print.EndPage(dc)
            finally:
                page.close()
        win32print.EndDoc(dc)
        return job_id
    except Exception as exc:
        if job_id and job_id > 0:
            try:
                win32print.AbortDoc(dc)
            except Exception:
                pass
        raise PrintJobError(str(exc), index, job_id) from exc
    finally:
        if dc:
            win32gui.DeleteDC(dc)


def draw_form_fields(raw, hdc, document, page, x, y, width, height):
    import pypdfium2 as pdfium

    # Only the transparent form overlay is rasterized in normal printing.
    scale = min(width / page.get_width(), height / page.get_height(), 300 / 72)
    w = max(1, round(page.get_width() * scale))
    h = max(1, round(page.get_height() * scale))
    bitmap = pdfium.PdfBitmap.new_native(w, h, raw.FPDFBitmap_BGRA)
    try:
        bitmap.fill_rect(0, 0, w, h, (0, 0, 0, 0))
        raw.FPDF_FFLDraw(document.formenv.raw, bitmap.raw, page.raw, 0, 0, w, h, 0, raw.FPDF_PRINTING)
        overlay = bitmap.to_pil().convert("RGBA")
        if overlay.getchannel("A").getbbox() is None:
            return
        # Windows AlphaBlend honors transparency on printer drivers that support it.

        alpha_blend(hdc, overlay, x, y, width, height)
    finally:
        bitmap.close()


def alpha_blend(hdc, image, x, y, width, height):
    from ctypes import wintypes

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                    ("height", wintypes.LONG), ("planes", wintypes.WORD),
                    ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD), ("x_ppm", wintypes.LONG),
                    ("y_ppm", wintypes.LONG), ("used", wintypes.DWORD),
                    ("important", wintypes.DWORD)]

    gdi = ctypes.windll.gdi32
    blend = ctypes.windll.msimg32.AlphaBlend
    blend.argtypes = [ctypes.c_void_p, *([ctypes.c_int] * 4), ctypes.c_void_p,
                      *([ctypes.c_int] * 4), wintypes.DWORD]
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
    gdi.CreateDIBSection.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    w, h = image.size
    info = BitmapInfo(ctypes.sizeof(BitmapInfo), w, -h, 1, 32)
    data = ctypes.c_void_p()
    source = gdi.CreateCompatibleDC(hdc)
    if not source:
        raise RuntimeError("Không tạo được lớp hiển thị biểu mẫu.")
    bitmap = None
    previous = None
    try:
        bitmap = gdi.CreateDIBSection(source, ctypes.byref(info), 0, ctypes.byref(data), None, 0)
        if not bitmap:
            raise RuntimeError("Không tạo được ảnh biểu mẫu.")
        pixels = image.convert("RGBa").tobytes()
        bgra = bytearray(pixels)
        bgra[0::4], bgra[2::4] = pixels[2::4], pixels[0::4]
        ctypes.memmove(data, bytes(bgra), len(bgra))
        previous = gdi.SelectObject(source, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            raise RuntimeError("Không chọn được lớp ảnh biểu mẫu.")
        if not blend(hdc, x, y, width, height, source, 0, 0, w, h, 0x01FF0000):
            raise RuntimeError("Driver không hỗ trợ lớp trong suốt. Hãy thử lại dưới dạng ảnh.")
    finally:
        if previous and previous != ctypes.c_void_p(-1).value:
            gdi.SelectObject(source, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        gdi.DeleteDC(source)


def printable_margins(name, mode):
    import win32gui
    import win32print

    dc = win32gui.CreateDC("WINSPOOL", name, mode)
    try:
        width, height, dpi_x, dpi_y, total_w, total_h, left, top = (
            win32print.GetDeviceCaps(dc, value) for value in (8, 10, 88, 90, 110, 111, 112, 113)
        )
        if min(dpi_x, dpi_y, width, height) <= 0:
            raise RuntimeError("Không xác định được vùng in.")
        return (left * 25.4 / dpi_x, top * 25.4 / dpi_y,
                max(0, total_w - width - left) * 25.4 / dpi_x,
                max(0, total_h - height - top) * 25.4 / dpi_y)
    finally:
        win32gui.DeleteDC(dc)
