"""Local Vietnamese OCR and build-time staging for the Windows executable."""
import ctypes
from pathlib import Path
import os
import sys


WINDOWS_DLLS = ("tesseract50.dll", "leptonica-1.82.0.dll")
MODEL = "vie.traineddata"


class VietnameseOCR:
    def __init__(self, library, data_directory):
        pointer = ctypes.c_void_p
        string = ctypes.c_char_p
        integer = ctypes.c_int
        for name, result, args in (
            ("TessBaseAPICreate", pointer, []),
            ("TessBaseAPIDelete", None, [pointer]),
            ("TessBaseAPIInit4", integer, [pointer, string, string, integer,
                                          pointer, integer, pointer, pointer, ctypes.c_size_t, integer]),
            ("TessBaseAPISetPageSegMode", None, [pointer, integer]),
            ("TessBaseAPISetImage", None, [pointer, string, integer, integer, integer, integer]),
            ("TessBaseAPISetSourceResolution", None, [pointer, integer]),
            ("TessBaseAPIGetHOCRText", pointer, [pointer, integer]),
            ("TessDeleteText", None, [pointer]),
        ):
            function = getattr(library, name)
            function.restype = result
            function.argtypes = args
        self.library = library
        self.handle = library.TessBaseAPICreate()
        if not self.handle:
            raise RuntimeError("Không tạo được bộ nhận dạng chữ.")
        try:
            if library.TessBaseAPIInit4(self.handle, os.fsencode(data_directory), b"vie", 1,
                                        None, 0, None, None, 0, 0) != 0:
                raise RuntimeError("Không nạp được dữ liệu OCR tiếng Việt.")
        except Exception:
            self.close()
            raise

    def recognize(self, image, dpi, *, page_seg_mode=3):
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.tobytes()
        self.library.TessBaseAPISetPageSegMode(self.handle, page_seg_mode)
        self.library.TessBaseAPISetImage(self.handle, pixels, width, height, 1, width)
        self.library.TessBaseAPISetSourceResolution(self.handle, dpi)
        text = self.library.TessBaseAPIGetHOCRText(self.handle, 0)
        if not text:
            raise RuntimeError("Bộ OCR không xử lý được ảnh của trang này.")
        try:
            return ctypes.string_at(text).decode("utf-8", errors="replace")
        finally:
            self.library.TessDeleteText(text)

    def close(self):
        if self.handle:
            self.library.TessBaseAPIDelete(self.handle)
            self.handle = None


def windows_ocr(directory=None):
    if directory is None:
        directory = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "ocr"
    directory = directory.resolve()
    with os.add_dll_directory(str(directory)):
        library = ctypes.CDLL(str(directory / WINDOWS_DLLS[0]))
    return VietnameseOCR(library, directory)


def stage_windows_ocr(directory):
    """Download versioned Windows dependencies only when packaging the app."""
    from hashlib import sha1
    from io import BytesIO
    from urllib.request import urlopen
    from zipfile import ZipFile
    from PIL import Image, ImageDraw, ImageFont

    nuget = "https://api.nuget.org/v3-flatcontainer/tesseract/5.2.0/tesseract.5.2.0.nupkg"
    source = "https://raw.githubusercontent.com/tesseract-ocr"
    urls = {
        MODEL: f"{source}/tessdata_best/4.1.0/vie.traineddata",
        "LICENSE-tesseract.txt": f"{source}/tesseract/5.2.0/LICENSE",
        "LICENSE-tessdata.txt": f"{source}/tessdata_best/4.1.0/LICENSE",
        "LICENSE-leptonica.txt": "https://raw.githubusercontent.com/DanBloomberg/leptonica/1.82.0/leptonica-license.txt",
    }
    directory.mkdir(parents=True, exist_ok=True)
    with urlopen(nuget, timeout=60) as response, ZipFile(BytesIO(response.read())) as archive:
        for dll in WINDOWS_DLLS:
            member = next((name for name in archive.namelist()
                           if Path(name).name.lower() == dll and "x64" in Path(name).parts), None)
            if member is None:
                raise RuntimeError(f"Không tìm thấy {dll} (x64) trong gói Tesseract.")
            (directory / dll).write_bytes(archive.read(member))
    for name, url in urls.items():
        with urlopen(url, timeout=60) as response:
            content = response.read()
        if name == MODEL and sha1(f"blob {len(content)}\0".encode() + content).hexdigest() != (
            "28bc301dc848861eb6ba734b866152b2a04732fc"
        ):
            raise RuntimeError("Dữ liệu OCR tiếng Việt tải về không đúng phiên bản.")
        (directory / name).write_bytes(content)
    engine = windows_ocr(directory)
    try:
        sample = Image.new("L", (660, 120), 255)
        ImageDraw.Draw(sample).text((30, 30), "VAN BAN THU NGHIEM", fill=0,
                                    font=ImageFont.load_default(size=44))
        # Verify the OCR API and page geometry, regardless of how the model spells this sample.
        markup = engine.recognize(sample, 150, page_seg_mode=7)
        if "ocr_page" not in markup or "bbox" not in markup:
            raise RuntimeError("Bộ OCR đóng gói không trả về dữ liệu bố cục hOCR.")
        if "ocrx_word" not in markup:
            print("Cảnh báo: OCR đã trả bố cục trang nhưng chưa nhận ra chữ trong ảnh thử.")
    finally:
        engine.close()
    return WINDOWS_DLLS, tuple(urls)
