from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def version_key(version: str) -> tuple[int, int, int]:
    part = r"(0|[1-9][0-9]*)"
    match = re.fullmatch(rf"{part}\.{part}\.{part}", version)
    if not match:
        raise ValueError(f"Số phiên bản không hợp lệ ({version}).")
    return tuple(map(int, match.groups()))


config = ConfigParser()
config.read(Path(__file__).with_name("version.ini"), encoding="ascii")
APP_VERSION = config["app"]["version"]
version_key(APP_VERSION)
REPOSITORY = "NguyenHuyenTri/trihx-pdf"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "TRIHX-PDF-Reader-Windows-x64.exe"
VERSIONS_DIR = "trihx-versions"
READER_NAME = "HX PDF.exe"


@dataclass(frozen=True)
class Release:
    version: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"https://github.com/{REPOSITORY}/releases/download/v{self.version}/{ASSET_NAME}"


def available_update(data: dict, current: str = APP_VERSION) -> Release | None:
    if not isinstance(data, dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise ValueError("Thông tin bản phát hành chính thức không hợp lệ.")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("Bản phát hành thiếu số phiên bản.")
    version = tag[1:]
    if version_key(version) <= version_key(current):
        return None
    for asset in data.get("assets", []):
        if asset.get("name") != ASSET_NAME or asset.get("state") != "uploaded":
            continue
        size = asset.get("size")
        digest = re.fullmatch(r"sha256:([0-9a-f]{64})", asset.get("digest") or "")
        if type(size) is int and size > 0 and digest:
            return Release(version, size, digest[1])
    raise ValueError("Bản phát hành chưa có gói cập nhật Windows x64 kèm mã kiểm tra. Hãy thử lại sau.")


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        hosts = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com", "github-releases.githubusercontent.com"}
        if (target.scheme != "https" or target.hostname not in hosts or
                target.port not in (None, 443) or target.username is not None):
            raise ValueError("GitHub trả về địa chỉ tải không hợp lệ.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url, accept):
    request = Request(url, headers={"Accept": accept, "User-Agent": f"TRIHX-PDF/{APP_VERSION}"})
    return build_opener(GitHubRedirect()).open(request, timeout=15)


def check_for_update() -> Release | None:
    try:
        with open_url(LATEST_URL, "application/vnd.github+json") as response:
            metadata = response.read(1024 * 1024 + 1)
            if len(metadata) > 1024 * 1024:
                raise ValueError("Thông tin phiên bản vượt quá kích thước cho phép.")
            return available_update(json.loads(metadata))
    except HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise ValueError("Chưa tìm thấy bản phát hành công khai. Hãy thử lại sau.") from exc
        raise


def versions_directory(executable: Path) -> Path:
    if executable.parent.parent.name == VERSIONS_DIR:
        return executable.parent.parent
    # A standalone reader might be in Downloads or a shared folder. Only use
    # updates in this user's data directory, scoped to that portable executable.
    identity = hashlib.sha256(os.fsencode(os.path.normcase(str(executable)))).hexdigest()
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "TRIHX" / "Portable" / identity / VERSIONS_DIR


def update_directory() -> Path:
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        raise ValueError("Bạn đang chạy từ mã nguồn. Hãy dùng capnhat.bat để cập nhật bản tự dựng.")
    return versions_directory(Path(sys.executable).resolve())


def installed_versions(directory: Path):
    readers = []
    for reader in directory.glob("*/" + READER_NAME):
        try:
            version = version_key(reader.parent.name)
        except ValueError:
            continue
        if reader.is_file():
            readers.append((version, reader))
    return sorted(readers, reverse=True)


def refresh_installed_launcher(reader: Path, root: Path, bundled: Path) -> bool:
    """Refresh only the registered installation's launcher, keeping all shortcut targets valid."""
    from PySide6.QtCore import QLockFile

    versions = root / VERSIONS_DIR
    launcher = root / READER_NAME
    if reader != versions / APP_VERSION / READER_NAME or not launcher.is_file():
        return False
    lock = QLockFile(str(root / ".trihx-launcher.lock"))
    if not lock.tryLock(1000):
        return False
    temporary = None
    try:
        newest = installed_versions(versions)
        if not newest or newest[0][1] != reader:
            return False
        contents = bundled.read_bytes()
        if launcher.stat().st_size == len(contents) and launcher.read_bytes() == contents:
            return False
        with tempfile.NamedTemporaryFile(dir=root, prefix="trihx-launcher-", suffix=".tmp",
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, launcher)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlock()


def refresh_windows_icons(launcher: Path, reader: Path, launcher_changed: bool):
    """Point the existing application links at the active icon while keeping their launch target."""
    import ctypes
    import pythoncom
    from win32com import storagecon
    from win32com.shell import shell, shellcon

    notify = ctypes.windll.shell32.SHChangeNotify
    if launcher_changed:
        _, image = shell.SHGetFileInfo(str(launcher), 0, shellcon.SHGFI_SYSICONINDEX)
        ctypes.windll.shell32.SHUpdateImageW(ctypes.c_wchar_p(str(launcher)), 0, 0, image[1])
        notify(shellcon.SHCNE_UPDATEITEM, shellcon.SHCNF_PATHW | shellcon.SHCNF_FLUSH,
               ctypes.c_wchar_p(str(launcher)), None)

    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, 0, 0))
    programs = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, 0, 0))
    for path in (desktop / "TRIHX PDF.lnk", programs / "TRIHX PDF" / "TRIHX PDF.lnk"):
        if not path.is_file():
            continue
        try:
            link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
            file = link.QueryInterface(pythoncom.IID_IPersistFile)
            file.Load(str(path), storagecon.STGM_READWRITE)
            if Path(link.GetPath(0)[0]) != launcher:
                continue
            icon, index = link.GetIconLocation()
            previous = Path(os.path.expandvars(icon))
            if previous == reader or index != 0:
                continue
            if icon and previous != launcher and not (previous.name == READER_NAME and previous.parent.parent == reader.parent.parent):
                continue  # Preserve a custom shortcut icon selected by the user.
            link.SetIconLocation(str(reader), 0)
            file.Save(str(path), True)
            notify(shellcon.SHCNE_UPDATEITEM, shellcon.SHCNF_PATHW | shellcon.SHCNF_FLUSH,
                   ctypes.c_wchar_p(str(path)), None)
        except (OSError, pythoncom.com_error):
            continue  # A locked or redirected link can be refreshed on a later launch.


def matches_release(path: Path, release: Release) -> bool:
    try:
        if path.stat().st_size != release.size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == release.sha256
    except FileNotFoundError:
        return False


def stage_update(release: Release, directory: Path, progress, cancelled) -> Path:
    version_key(release.version)
    folder = directory / release.version
    target = folder / READER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    if matches_release(target, release):
        return target
    partial = None
    received = 0
    previous_percent = -1
    digest = hashlib.sha256()
    try:
        with open_url(release.url, "application/octet-stream") as response:
            with tempfile.NamedTemporaryFile(dir=folder, prefix="reader-", suffix=".part",
                                             delete=False) as output:
                partial = Path(output.name)
                while not cancelled():
                    chunk = response.read1(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > release.size:
                        raise ValueError("Dung lượng gói cập nhật tải về khác bản phát hành.")
                    output.write(chunk)
                    digest.update(chunk)
                    percent = received * 100 // release.size
                    if percent != previous_percent:
                        progress(percent)
                        previous_percent = percent
                output.flush()
                os.fsync(output.fileno())
        if cancelled():
            raise InterruptedError("Đã hủy tải bản cập nhật.")
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("Gói cập nhật tải về thiếu dữ liệu hoặc sai mã kiểm tra. Hãy thử lại.")
        try:
            os.replace(partial, target)
        except PermissionError:
            # Another reader can finish the same update and open it first.
            if not matches_release(target, release):
                raise
        return target
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def start_reader(path: Path, arguments: list[str]):
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        import ctypes

        # A portable reader can start a newer independent PyInstaller process.
        set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        if not set_dll_directory(None):
            raise ctypes.WinError()
        root = Path(bundle)
        env["PATH"] = os.pathsep.join(entry for entry in env.get("PATH", "").split(os.pathsep)
                                     if not Path(entry).is_relative_to(root))
    try:
        subprocess.Popen([str(path), *arguments], env=env)
    finally:
        if bundle:
            set_dll_directory(bundle)


def forward_portable_launch(executable: Path, arguments: list[str]) -> bool:
    if executable.parent.parent.name == VERSIONS_DIR:
        return False
    for version, reader in installed_versions(versions_directory(executable)):
        if version <= version_key(APP_VERSION):
            break
        try:
            start_reader(reader, arguments)
        except OSError:
            continue
        return True
    return False


def clean_old_versions(directory: Path):
    # Keep the previous working version. An older, open reader can finish on its own.
    older = [reader for version, reader in installed_versions(directory) if version < version_key(APP_VERSION)]
    for reader in older[1:]:
        try:
            reader.unlink()
            reader.parent.rmdir()
        except OSError:
            pass
    cutoff = time.time() - 86400
    for partial in directory.glob("*/reader-*.part"):
        try:
            if partial.stat().st_mtime < cutoff:
                partial.unlink()
        except OSError:
            pass
