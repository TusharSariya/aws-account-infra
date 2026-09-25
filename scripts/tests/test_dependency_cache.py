import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock

from dependency_cache import BASE, IntegrityError, key, pack, run, transfer, unpack


class FakeNexus:
    """Serve stored archives by URL and record uploads; unknown URLs are 404."""

    def __init__(self, store=None):
        self.store = dict(store or {})
        self.requested, self.uploaded = [], []

    def open(self, target, timeout=None):
        if isinstance(target, str):
            self.requested.append(target)
            if target not in self.store:
                raise urllib.error.HTTPError(target, 404, "missing", {}, None)
            return io.BytesIO(self.store[target])
        self.uploaded.append(target.full_url)
        return io.BytesIO()


class FallbackAndSkipTests(unittest.TestCase):
    ARGS = ("python", "uv-python-3.14", "hash")

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "source"
        source.mkdir()
        (source / "wheel").write_bytes(b"public wheel")
        self.archive = pack(source)
        self.directory = self.root / "cache"
        self.directory.mkdir()
        self.env_file = self.root / "github_env"

    def url(self, branch):
        return BASE + key(*self.ARGS, branch, scope="job/") + ".zip"

    def restore(self, branch, nexus):
        return run("restore", *self.ARGS, branch, self.directory, scope="job/",
                   env_file=self.env_file, opener=nexus)

    def exported(self):
        lines = self.env_file.read_text().splitlines()
        return dict(line.split("=", 1) for line in lines)

    def test_branch_miss_falls_back_to_main_read_only(self):
        nexus = FakeNexus({self.url("main"): self.archive})
        receipt = self.restore("feature/cache", nexus)
        self.assertEqual(receipt["result"], "hit")
        self.assertEqual(receipt["fallback"], "main")
        self.assertEqual(nexus.requested, [self.url("feature/cache"), self.url("main")])
        self.assertEqual((self.directory / "wheel").read_bytes(), b"public wheel")
        marker = self.exported()["HOMELAB_DEPENDENCY_CACHE_HIT_PYTHON"]
        self.assertEqual(marker, key(*self.ARGS, "feature/cache", scope="job/"))
        # Without a hit marker a save uploads, and only ever to the branch key.
        run("save", *self.ARGS, "feature/cache", self.directory, scope="job/",
            password="secret", environ={}, opener=nexus)
        self.assertEqual(nexus.uploaded, [self.url("feature/cache")])

    def test_branch_hit_does_not_consult_main(self):
        nexus = FakeNexus({self.url("feature/cache"): self.archive,
                           self.url("main"): b"never read"})
        receipt = self.restore("feature/cache", nexus)
        self.assertEqual(receipt["result"], "hit")
        self.assertNotIn("fallback", receipt)
        self.assertEqual(nexus.requested, [self.url("feature/cache")])

    def test_main_never_falls_back_and_misses_export_no_marker(self):
        nexus = FakeNexus()
        self.assertEqual(self.restore("main", nexus)["result"], "miss")
        self.assertEqual(nexus.requested, [self.url("main")])
        self.assertNotIn("HOMELAB_DEPENDENCY_CACHE_HIT_PYTHON", self.exported())
        self.assertEqual(self.exported()["UV_CACHE_DIR"], str(self.directory))
        nexus = FakeNexus()
        self.assertEqual(self.restore("feature/cache", nexus)["result"], "miss")
        self.assertEqual(nexus.requested, [self.url("feature/cache"), self.url("main")])

    def test_save_after_hit_is_skipped_without_packing(self):
        nexus = FakeNexus({self.url("main"): self.archive})
        self.restore("feature/cache", nexus)
        (self.directory / "credentials").write_text("would fail packing")
        receipt = run("save", *self.ARGS, "feature/cache", self.directory,
                      scope="job/", password="secret", environ=self.exported(),
                      opener=nexus)
        self.assertEqual(receipt["result"], "unchanged")
        self.assertEqual(nexus.uploaded, [])

    def test_save_with_stale_marker_still_uploads(self):
        nexus = FakeNexus()
        environ = {"HOMELAB_DEPENDENCY_CACHE_HIT_PYTHON": key(*self.ARGS, "other", scope="job/")}
        receipt = run("save", *self.ARGS, "feature/cache", self.directory,
                      scope="job/", password="secret", environ=environ, opener=nexus)
        self.assertEqual(receipt["result"], "saved")
        self.assertEqual(nexus.uploaded, [self.url("feature/cache")])


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
