"""Atomic, checksum-verified model cache for Talos CPU backends only."""

import hashlib
import os
from pathlib import Path
import re
import tempfile
import urllib.request


def cache_model(url, checksum, destination):
    destination = Path(destination)
    if not re.fullmatch(r"[a-f0-9]{64}", checksum) or not url.startswith("https://"):
        raise ValueError("Require HTTPS and a pinned SHA256")
    if destination.is_file():
        with destination.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == checksum:
                return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(url, timeout=30) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("Insecure redirect")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024**3:
                        raise ValueError("Validation model exceeds 2 GiB")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != checksum:
                raise ValueError("Model checksum mismatch")
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o644)
        os.replace(temporary, destination)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    cache_model(
        os.environ["MODEL_URL"], os.environ["MODEL_SHA256"], os.environ["MODEL_PATH"]
    )
