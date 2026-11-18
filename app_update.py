from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
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
ASSET_NAME = "TRIHX-PDF-Setup-Windows-x64.exe"


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
    raise ValueError("Bản phát hành chưa có bộ cài Windows x64 kèm mã kiểm tra. Hãy thử lại sau.")


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


def download_installer(release: Release, directory: Path, progress, cancelled) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    partial = None
    received = 0
    previous_percent = -1
    digest = hashlib.sha256()
    try:
        with open_url(release.url, "application/octet-stream") as response:
            with tempfile.NamedTemporaryFile(dir=directory, prefix="trihx-setup-", suffix=".part",
                                             delete=False) as output:
                partial = Path(output.name)
                while not cancelled():
                    chunk = response.read1(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > release.size:
                        raise ValueError("Dung lượng bộ cài tải về khác bản phát hành.")
                    output.write(chunk)
                    digest.update(chunk)
                    percent = received * 100 // release.size
                    if percent != previous_percent:
                        progress(percent)
                        previous_percent = percent
        if cancelled():
            raise InterruptedError("Đã hủy tải bản cập nhật.")
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("Bộ cài tải về thiếu dữ liệu hoặc sai mã kiểm tra. Hãy tải lại.")
        return partial.rename(partial.with_suffix(".exe"))
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def launch_installer(path: Path):
    if sys.platform != "win32":
        raise OSError("Bộ cài này dùng cho Windows 10/11 x64.")
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        import ctypes

        # The setup wizard and the reader it starts must outlive this one-file bundle.
        set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        if not set_dll_directory(None):
            raise ctypes.WinError()
        root = Path(bundle)
        env["PATH"] = os.pathsep.join(entry for entry in env.get("PATH", "").split(os.pathsep)
                                     if not Path(entry).is_relative_to(root))
    try:
        subprocess.Popen([str(path)], cwd=path.parent, env=env)
    finally:
        if bundle:
            set_dll_directory(bundle)
