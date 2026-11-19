import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_update import (
    ASSET_NAME, READER_NAME, GitHubRedirect, Release, available_update,
    clean_old_versions, forward_portable_launch, installed_versions, stage_update, versions_directory,
)


class UpdateTests(unittest.TestCase):
    payload = b"reader fixture"

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
            return stage_update(self.release, self.directory, lambda n: None, cancelled)

    def test_only_verified_bytes_are_visible_to_the_launcher(self):
        for payload in (self.payload[:-1], b"X" * len(self.payload), self.payload + b"x"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.download(payload)
            self.assertEqual(installed_versions(self.directory), [])
            self.assertFalse(list(self.directory.rglob("*.part")))
        with self.assertRaises(InterruptedError):
            self.download(self.payload, cancelled=lambda: True)
        self.assertEqual(installed_versions(self.directory), [])
        reader = self.download(self.payload)
        self.assertEqual(reader, self.directory / self.release.version / READER_NAME)
        self.assertEqual(reader.read_bytes(), self.payload)
        with patch("app_update.open_url", side_effect=AssertionError("downloaded twice")):
            self.assertEqual(stage_update(self.release, self.directory, self.fail, lambda: False), reader)

    def test_portable_launch_and_old_version_cleanup(self):
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": str(self.directory / "user data")}))
        portable = self.directory / "Reader renamed.exe"
        versions = versions_directory(portable)
        self.assertNotEqual(versions, versions_directory(self.directory / READER_NAME))
        self.assertFalse(versions.is_relative_to(portable.parent / "trihx-versions"))
        for name in ("0.1.0", "0.2.0", "0.3.0", "0.9.0", "0.10.0", "unfinished"):
            folder = versions / name
            folder.mkdir(parents=True)
            (folder / READER_NAME).write_bytes(self.payload)
        highest = versions / "0.10.0" / READER_NAME
        with patch("app_update.APP_VERSION", "0.3.0"), patch("app_update.start_reader") as start:
            self.assertTrue(forward_portable_launch(portable, ["a b.pdf"]))
            start.assert_called_once_with(highest, ["a b.pdf"])
            self.assertFalse(forward_portable_launch(highest, ["a b.pdf"]))
            clean_old_versions(versions)
        self.assertEqual([v for v, _ in installed_versions(versions)], [(0, 10, 0), (0, 9, 0), (0, 3, 0), (0, 2, 0)])
        self.assertTrue((versions / "unfinished" / READER_NAME).is_file())
