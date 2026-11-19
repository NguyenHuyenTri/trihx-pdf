# -*- mode: python ; coding: utf-8 -*-
import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

datas = collect_data_files("pypdfium2")
datas += [("app_icon.png", "."), ("version.ini", ".")]
binaries = collect_dynamic_libs("pypdfium2")

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

# The installed shortcut stays at the same path while reader versions coexist.
# The regular dist/HX PDF.exe remains usable on its own as a portable reader.
if sys.platform == "win32":
    root = Path(SPECPATH)
    launcher = root / "build" / "launcher" / "HX PDF.exe"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/codepage:65001",
                    "/reference:System.Windows.Forms.dll", "/win32icon:" + str(root / "app_icon.ico"),
                    "/out:" + str(launcher), str(root / "reader_launcher.cs")], check=True)
