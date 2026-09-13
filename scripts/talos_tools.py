"""Pinned Talos deployment tools and chart acquisition; no cluster access."""
import hashlib
import io
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/talos/homelab'
VERSION = 'v1.13.9'
HASHES = {
    ('Darwin', 'arm64'): 'ab4c27a959ff6c52f62c6cc2af07b22ca86ed27f1a138ed57582fa67f7b50f98',
    ('Linux', 'x86_64'): '7e1d4b7d5846964bdcf63a794e3c8161bb6ef2983d5ace58ea5322f3bf32a27e',
}


def private_dir(path):
    path = path.expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError('Secret/output directories must be outside the repository')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Directory must be owned by this user with mode 0700')
    return path


def cli():
    system = (platform.system(), platform.machine())
    if system not in HASHES:
        raise ValueError('Supported administration platforms: macOS arm64, Linux amd64')
    asset = 'talosctl-' + ('darwin-arm64' if system[0] == 'Darwin' else 'linux-amd64')
    cache = private_dir(Path.home() / '.cache/aws-account-infra/talos')
    binary = cache / (asset + '-' + VERSION)
    if not binary.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                with urllib.request.urlopen(f'https://github.com/siderolabs/talos/releases/download/{VERSION}/{asset}', timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                stream.flush()
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != HASHES[system]:
                    raise ValueError('Downloaded talosctl checksum mismatch')
                temporary.chmod(0o700)
                temporary.replace(binary)
            finally:
                temporary.unlink(missing_ok=True)
    if binary.is_symlink() or hashlib.sha256(binary.read_bytes()).hexdigest() != HASHES[system]:
        raise ValueError('Cached talosctl checksum mismatch')
    return binary


def download_verified(url, destination, expected):
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Downloaded artifact checksum mismatch')
    destination.write_bytes(data)


def prepare_local_path_chart():
    data = urllib.request.urlopen(
        'https://codeload.github.com/rancher/local-path-provisioner/tar.gz/refs/tags/v0.0.37', timeout=60).read()
    if hashlib.sha256(data).hexdigest() != '3602edf85bb1513d463073917adc930752177d034e1f944fb8f7610c779a34f6':
        raise ValueError('Local-path source checksum mismatch')
    prefix = 'local-path-provisioner-0.0.37/deploy/chart/local-path-provisioner/'
    destination = TF / '.terraform/local-path-provisioner'
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.startswith(prefix):
                relative = Path(member.name[len(prefix):])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe chart archive path')
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())


def setup(acceptance=False, charts=True):
    binary = cli()
    if charts:
        (TF / '.terraform').mkdir(parents=True, exist_ok=True)
        download_verified('https://helm.cilium.io/cilium-1.20.1.tgz',
                          TF / '.terraform/cilium-1.20.1.tgz',
                          '06210eef7c23d15f7699c79e2fe3a1ec9c389024c5c5c006ea04022d322449a2')
        prepare_local_path_chart()
    if acceptance:
        if platform.system() != 'Linux' or platform.machine() != 'x86_64':
            raise ValueError('CI acceptance requires Linux amd64')
        kubectl = binary.parent / 'kubectl-v1.36.3'
        download_verified('https://dl.k8s.io/release/v1.36.3/bin/linux/amd64/kubectl', kubectl,
                          'ebbd080e7c2e275093b55915722043257eb24004363e20acb3c4d71919f88336')
        kubectl.chmod(0o700)
    return binary
