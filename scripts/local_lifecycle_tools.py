"""Checksum-pinned Mac administration tools, isolated inside the local record."""
import hashlib
import io
import os
import platform
from pathlib import Path
import urllib.request
import zipfile

KUBECTL_SHA = 'fc8582acde13869a606730a79379d6515f30c68afcced0b5ac8789d5d002b7d6'
TOFU_ZIP_SHA = 'ce81702643dcdea497259b4de4639d9ee73746560683b9d2b778aae8f7d62827'


def verified_file(path, url, digest):
    if path.is_symlink():
        raise ValueError('Local tool must not be a symlink')
    if not path.exists():
        payload = urllib.request.urlopen(url, timeout=120).read()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError('Local tool download checksum mismatch')
        path.write_bytes(payload)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Local tool checksum mismatch')
    return path.read_bytes()


def setup(directory):
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise ValueError('Local runner currently pins macOS arm64 tools')
    directory = Path(directory) / 'tools'
    directory.mkdir(mode=0o700, exist_ok=True)
    kubectl = directory / 'kubectl'
    verified_file(kubectl, 'https://dl.k8s.io/release/v1.36.3/bin/darwin/arm64/kubectl', KUBECTL_SHA)
    kubectl.chmod(0o700)
    archive = verified_file(directory / 'tofu.zip',
        'https://github.com/opentofu/opentofu/releases/download/v1.11.5/tofu_1.11.5_darwin_arm64.zip', TOFU_ZIP_SHA)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        binary = source.read('tofu')
    tofu = directory / 'tofu'
    if tofu.is_symlink() or (tofu.exists() and tofu.read_bytes() != binary):
        raise ValueError('Local OpenTofu binary changed')
    if not tofu.exists():
        tofu.write_bytes(binary)
    tofu.chmod(0o700)
    os.environ['PATH'] = str(directory) + os.pathsep + os.environ['PATH']
    return str(kubectl)
