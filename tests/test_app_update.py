import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_update import ASSET_NAME, GitHubRedirect, Release, available_update, download_installer


class UpdateTests(unittest.TestCase):
    payload = b"installer fixture"

    def setUp(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        self.release = Release("0.10.0", len(self.payload), digest)
        self.asset = dict(name=ASSET_NAME, state="uploaded", size=len(self.payload), digest=f"sha256:{digest}")
        self.metadata = dict(tag_name="v0.10.0", draft=False, prerelease=False, assets=[self.asset])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_stable_versions_compare_numerically(self):
        self.assertEqual(available_update(self.metadata, "0.9.9"), self.release)
        for version in ("0.10.0", "1.0.0"):
            self.assertIsNone(available_update(self.metadata, version))
        for fields in ({"draft": True}, {"prerelease": True}, {"tag_name": "v1.0.0-rc1"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                available_update(self.metadata | fields, "0.9.9")

    def test_requires_complete_windows_asset_and_digest(self):
        for fields in ({"size": 0}, {"digest": None}, {"digest": "md5:abc"}, {"name": "other.exe"}, {"state": "new"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                available_update(self.metadata | {"assets": [self.asset | fields]}, "0.9.9")
        for url in ("http://github.com/example", "https://example.org/test", "https://github.com.example.org/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                GitHubRedirect().redirect_request(None, None, 302, "", {}, url)

    def download(self, payload, cancelled=lambda: False):
        with patch("app_update.open_url", return_value=io.BytesIO(payload)):
            return download_installer(self.release, self.directory, lambda n: None, cancelled)

    def test_only_verified_bytes_become_an_installer(self):
        for payload in (self.payload[:-1], b"X" * len(self.payload), self.payload + b"x"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.download(payload)
            self.assertEqual(list(self.directory.iterdir()), [])
        with self.assertRaises(InterruptedError):
            self.download(self.payload, cancelled=lambda: True)
        self.assertEqual(list(self.directory.iterdir()), [])
        installer = self.download(self.payload)
        self.assertEqual(installer.suffix, ".exe")
        self.assertEqual(installer.read_bytes(), self.payload)
        self.assertEqual(list(self.directory.iterdir()), [installer])
