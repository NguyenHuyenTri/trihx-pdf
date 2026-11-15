# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files
from pathlib import Path
from runpy import run_path
import sys

datas = collect_data_files("pypdfium2")
datas += [("app_icon.png", ".")]
binaries = collect_dynamic_libs("pypdfium2")
if sys.platform == "win32":
    stage_windows_ocr = run_path(str(Path(SPECPATH) / "scan_ocr.py"))["stage_windows_ocr"]
    ocr_directory = Path(workpath).resolve() / "ocr-stage"
    libraries, resources = stage_windows_ocr(ocr_directory)
    binaries += [(str(ocr_directory / library), "ocr") for library in libraries]
    datas += [(str(ocr_directory / resource), "ocr") for resource in resources]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["pypdfium2", "PIL.Image", "PIL.ImageWin", "win32print", "win32gui"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HX PDF",
    icon="app_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
