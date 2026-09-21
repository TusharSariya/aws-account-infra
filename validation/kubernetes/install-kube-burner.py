#!/usr/bin/env python3
"""Install the reviewed Linux x86_64 binary without root or shell pipelines."""

import hashlib
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

VERSION = "2.8.5"
SHA256 = "56c5b91a573782c9b6dbcdcb14e0c859403652129c1516efdf247825ec08d766"


def main():
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise SystemExit("This installer is for the Ubuntu x86_64 laptop")
    url = f"https://github.com/kube-burner/kube-burner/releases/download/v{VERSION}/kube-burner-V{VERSION}-linux-x86_64.tar.gz"
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "release.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise SystemExit("Release checksum mismatch")
        destination = Path.home() / ".local/bin/kube-burner"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as release:
            member = next(
                m for m in release if m.isfile() and Path(m.name).name == "kube-burner"
            )
            data = release.extractfile(member).read()
        tmp = destination.with_suffix(".new")
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        tmp.replace(destination)
        print(f"Installed kube-burner {VERSION}: {destination}")


if __name__ == "__main__":
    main()
