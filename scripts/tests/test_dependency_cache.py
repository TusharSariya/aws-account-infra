import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock

from dependency_cache import IntegrityError, key, pack, transfer, unpack


class ArchiveTests(unittest.TestCase):
    def test_warm_restore_and_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "source", Path(temp) / "target"
            source.mkdir()
            (source / "module").write_bytes(b"public dependency")
            body = pack(source)
            unpack(body, target)
            self.assertEqual((target / "module").read_bytes(), b"public dependency")
            with self.assertRaises(IntegrityError):
                unpack(b"not a zip", target)
            self.assertEqual((target / "module").read_bytes(), b"public dependency")

    def test_python_cache_excludes_uv_environments_but_keeps_wheels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "cache"
            wheel = root / "archive-v0/wheel/yaml/__init__.py"
            wheel.parent.mkdir(parents=True)
            wheel.write_bytes(b"public wheel")
            environment = root / "archive-v0/environment"
            environment.mkdir()
            (environment / "pyvenv.cfg").write_text("home = /usr/bin")
            (environment / "python").symlink_to("/usr/bin/python3")
            environments = root / "environments-v2"
            environments.mkdir()
            (environments / "link").symlink_to(environment)
            source = root / "sdists-v9"
            source.mkdir()
            (source / ".git").write_text("uv cache boundary")
            target = Path(temp) / "restored"
            unpack(pack(root, kind="python"), target)
            self.assertEqual(
                (target / "archive-v0/wheel/yaml/__init__.py").read_bytes(),
                b"public wheel",
            )
            self.assertFalse((target / "archive-v0/environment").exists())
            self.assertFalse((target / "environments-v2").exists())
            self.assertFalse((target / "sdists-v9").exists())
            (root / "unexpected-link").symlink_to("/etc/passwd")
            with self.assertRaises(IntegrityError):
                pack(root, kind="python")

    def test_key_isolation(self):
        args = ["go", "1.26", "hash", "main", "Linux", "x86_64"]
        baseline = key(*args)
        for index in range(1, len(args)):
            altered = args.copy()
            altered[index] += "-different"
            self.assertNotEqual(key(*altered), baseline)

    def test_unavailable_and_denied_uploads_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as temp:
            for mode in ["restore", "save"]:
                opener = Mock()
                opener.open.side_effect = urllib.error.HTTPError(
                    "url", 403, "denied", {}, None
                )
                self.assertEqual(
                    transfer(mode, "key", Path(temp), "secret", opener)["result"],
                    "unavailable",
                )

    def test_credentials_and_links_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "credentials").write_text("secret")
            with self.assertRaises(IntegrityError):
                pack(root)
            (root / "credentials").unlink()
            (root / "link").symlink_to("/etc/passwd")
            with self.assertRaises(IntegrityError):
                pack(root)

    def test_unsafe_members_and_modified_bytes_are_fatal(self):
        for name, digest in [("../escape", "bad"), ("file", "bad")]:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format": 1,
                            "files": {name: {"sha256": digest, "mode": 0o644}},
                        }
                    ),
                )
                archive.writestr("data/" + name, b"data")
            with (
                tempfile.TemporaryDirectory() as temp,
                self.assertRaises(IntegrityError),
            ):
                unpack(stream.getvalue(), Path(temp) / "out")
