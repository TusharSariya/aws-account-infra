"""Single-purpose collectors; each service account writes one named status object."""
import json
import os
from pathlib import Path
import ssl
import time
import urllib.request
import uuid
import fcntl

from xfs import assign_empty_directory, get_quota, open_mount, open_project, set_limit

TOKEN = Path('/var/run/secrets/kubernetes.io/serviceaccount/token')
CA = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
PROJECTS = {'models': ('ai-models', 31001, 300 * 1024**3),
            'workspace': ('ai-workspace', 31002, 20 * 1024**3),
            'vector': ('ai-vector', 31003, 10 * 1024**3)}


def filesystem_uuid(fd):
    # Linux XFS_IOC_FSGEOMETRY_V1: 112 bytes; UUID follows 8 u32 and 4 u64.
    geometry = fcntl.ioctl(fd, 0x80705864, bytes(112))
    return str(uuid.UUID(bytes=geometry[64:80]))


def guest(config):
    expected = str(uuid.UUID(config['filesystemUUID']))  # no automatic trust enrollment
    fd = open_mount('/var/mnt/local-path-provisioner', '/dev/sdb1')
    try:
        if filesystem_uuid(fd) != expected:
            raise ValueError('Filesystem UUID mismatch')
        sample = {}
        for name, (directory, project, limit) in PROJECTS.items():
            project_fd = open_project(fd, directory)
            try:
                assign_empty_directory(project_fd, project)
                set_limit(fd, project, limit)
                # Keep the mount root owned by platform root. Applications can
                # write via group 1000 but cannot rename the root from its parent.
                os.fchown(project_fd, 0, 1000)
                os.fchmod(project_fd, 0o770)
                usage = get_quota(fd, project)
                sample[name] = {'identity': str(project), 'healthy': True,
                                'measured_at': time.time(), 'used_percent': 100 * usage.blocks * 512 / limit,
                                'used_bytes': usage.blocks * 512, 'used_inodes': usage.inodes,
                                'hard_limit_bytes': limit}
            finally:
                os.close(project_fd)
        stats = os.fstatvfs(fd)
        if stats.f_blocks <= 0 or stats.f_files <= 0:
            raise ValueError('Filesystem capacity unavailable')
        for name, used, total in [('filesystem.bytes', stats.f_blocks - stats.f_bavail, stats.f_blocks),
                                  ('filesystem.inodes', stats.f_files - stats.f_favail, stats.f_files)]:
            sample[name] = {'identity': expected, 'healthy': True, 'measured_at': time.time(),
                            'used_percent': 100 * used / total}
        return sample
    finally:
        os.close(fd)


def physical(config):
    # This dedicated CA and client key are mounted only in this collector.
    context = ssl.create_default_context(cafile='/physical-credentials/ca.crt')
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain('/physical-credentials/tls.crt', '/physical-credentials/tls.key')
    from urllib.parse import urlsplit
    parsed = urlsplit(config['physicalURL'])
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.path != '/capacity':
        raise ValueError('Explicit authenticated HTTPS capacity URL required')
    # Redirects are prohibited: the client certificate must stay on this host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Capacity redirects prohibited')
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())
    with opener.open(config['physicalURL'], timeout=10) as response:
        result = json.loads(response.read(65537))
    if set(result) != {'pool.data', 'pool.metadata'}:
        raise ValueError('Incomplete physical capacity response')
    if any(value.get('identity') != config['physicalPool'] for value in result.values()):
        raise ValueError('Wrong physical pool')
    # Preserve the sampler's original timestamps. Never refresh stale evidence.
    return result


def publish(mode, sample):
    context = ssl.create_default_context(cafile=CA)
    host = os.environ['KUBERNETES_SERVICE_HOST']
    port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    endpoint = f'https://{host}:{port}/api/v1/namespaces/homelab-platform/configmaps/{mode}-capacity'
    request = urllib.request.Request(endpoint, method='PATCH',
        headers={'Authorization': 'Bearer ' + TOKEN.read_text().strip(),
                 'Content-Type': 'application/merge-patch+json'},
        data=json.dumps({'data': {'sample.json': json.dumps(sample, allow_nan=False)}}).encode())
    with urllib.request.urlopen(request, context=context, timeout=10) as response:
        response.read()


def main():
    config = json.loads(Path('/config/config.json').read_text())
    mode = os.environ['COLLECTOR_MODE']
    collect = {'guest': guest, 'physical': physical}[mode]
    while True:
        start = time.monotonic()
        try:
            sample = collect(config)
        except Exception as error:
            sample = {}  # Absence fails admission closed. Never retain a fresh healthy timestamp.
            print(mode + ' capacity unavailable: ' + type(error).__name__, flush=True)
        try:
            publish(mode, sample)
        except Exception as error:
            print(mode + ' capacity publication failed: ' + type(error).__name__, flush=True)
        time.sleep(max(0, 30 - (time.monotonic() - start)))


if __name__ == '__main__':
    main()
