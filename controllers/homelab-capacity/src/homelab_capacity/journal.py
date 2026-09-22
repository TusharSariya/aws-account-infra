"""Private, crash-durable journals and a single laptop process owner."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_mode & 0o077:
            raise PermissionError("Journal directory must be private (0700)")

    @contextmanager
    def locked(self, name="coordinator.lock"):
        fd = os.open(self.path(name), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def read(self, name, default=None):
        path = self.path(name)
        return json.loads(path.read_text()) if path.exists() else default

    def path(self, name):
        if not name or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in name
        ):
            raise ValueError("Invalid journal name")
        return self.directory / name

    def write(self, name, value):
        path = self.path(name)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
