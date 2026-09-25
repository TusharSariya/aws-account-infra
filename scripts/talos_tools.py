"""Pinned Talos deployment tools and chart acquisition; no cluster access."""
import hashlib
import http.client
import io
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from cache_download import fetch

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/talos/homelab'
VERSION = 'v1.13.9'
HASHES = {
    ('Darwin', 'arm64'): 'ab4c27a959ff6c52f62c6cc2af07b22ca86ed27f1a138ed57582fa67f7b50f98',
    ('Linux', 'x86_64'): '7e1d4b7d5846964bdcf63a794e3c8161bb6ef2983d5ace58ea5322f3bf32a27e',
}
KUBECTL_VERSION = 'v1.36.3'
# Published dl.k8s.io/release/<version>/bin/<os>/<arch>/kubectl.sha256 values.
KUBECTL = {
    ('Darwin', 'arm64'): ('darwin/arm64', 'fc8582acde13869a606730a79379d6515f30c68afcced0b5ac8789d5d002b7d6'),
    ('Linux', 'x86_64'): ('linux/amd64', 'ebbd080e7c2e275093b55915722043257eb24004363e20acb3c4d71919f88336'),
}


def private_dir(path):
    path = path.expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError('Secret/output directories must be outside the repository')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Directory must be owned by this user with mode 0700')
    return path


def read_url(url, consume, timeout=60):
    """Retry only bounded read failures; callers still verify pinned checksums."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return consume(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            error.close()
        except (TimeoutError, ConnectionError, urllib.error.URLError, http.client.IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def cli():
    system = (platform.system(), platform.machine())
    if system not in HASHES:
        raise ValueError('Supported administration platforms: macOS arm64, Linux amd64')
    asset = 'talosctl-' + ('darwin-arm64' if system[0] == 'Darwin' else 'linux-amd64')
    cache = private_dir(Path.home() / '.cache/aws-account-infra/talos')
    binary = cache / (asset + '-' + VERSION)
    if not binary.exists() and os.environ.get('HOMELAB_DEPENDENCY_CACHE') == '1':
        fetch(f'https://github.com/siderolabs/talos/releases/download/{VERSION}/{asset}',
              HASHES[system], binary, use_cache=True)
        binary.chmod(0o700)
    if not binary.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                def write_download(response):
                    # A transport failure can happen after some bytes arrived.
                    stream.seek(0)
                    stream.truncate(0)
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                read_url(f'https://github.com/siderolabs/talos/releases/download/{VERSION}/{asset}',
                         write_download, timeout=120)
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
    if os.environ.get('HOMELAB_DEPENDENCY_CACHE') == '1':
        fetch(url, expected, destination, use_cache=True)
        return
    data = read_url(url, lambda response: response.read())
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Downloaded artifact checksum mismatch')
    destination.write_bytes(data)


def prepare_local_path_chart():
    with tempfile.TemporaryDirectory() as temporary:
        archive_path = Path(temporary) / 'chart.tar.gz'
        download_verified(
            'https://codeload.github.com/rancher/local-path-provisioner/tar.gz/refs/tags/v0.0.37',
            archive_path, '3602edf85bb1513d463073917adc930752177d034e1f944fb8f7610c779a34f6')
        data = archive_path.read_bytes()
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
        system = (platform.system(), platform.machine())
        if system not in KUBECTL:
            raise ValueError('CI acceptance requires Linux amd64 or macOS arm64')
        target, expected = KUBECTL[system]
        kubectl = binary.parent / f'kubectl-{KUBECTL_VERSION}'
        download_verified(f'https://dl.k8s.io/release/{KUBECTL_VERSION}/bin/{target}/kubectl',
                          kubectl, expected)
        kubectl.chmod(0o700)
    return binary
