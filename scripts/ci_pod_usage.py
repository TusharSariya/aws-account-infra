"""Read-only allocated-block accounting for a disposable runner Pod.

Run inside the isolated measurement observer, never inside a runner image.
Only metadata is read from workload files. Image manifests are the sole file
contents read from containerd; environment/config blobs are counted with stat.
This produces samples, not qualified cold/warm receipts or adopted budgets.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat as stat_mode
import time

UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SNAPSHOT = re.compile(r'/var/lib/containerd/io\.containerd\.snapshotter\.v1\.overlayfs/snapshots/[0-9]+/(?:fs|work)')


def overlay_paths(mountinfo):
    """Keep only the root overlay; nested Docker storage is already a volume."""
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(' - ')
        fields = before.split()
        tail = after.split()
        if not separator or len(fields) < 5 or fields[4] != '/' or tail[:1] != ['overlay']:
            continue
        options = dict(x.split('=', 1) for x in tail[2].split(',') if '=' in x)
        all_paths = [value for name in ('lowerdir', 'upperdir', 'workdir')
                     for value in options.get(name, '').split(':') if value]
        if all_paths and all(value.startswith(('/scratch/docker/', '/var/lib/buildkit/')) for value in all_paths):
            # Nested Docker/BuildKit roots are inside the already-counted scratch
            # volume. They still contribute CPU/RAM and deleted-open-file bytes.
            return []
        paths = []
        for name in ('lowerdir', 'upperdir', 'workdir'):
            for value in options.get(name, '').split(':'):
                if value:
                    if not SNAPSHOT.fullmatch(value):
                        raise ValueError('Unexpected containerd root overlay path')
                    paths.append(value)
        if not paths or 'upperdir' not in options or 'lowerdir' not in options:
            raise ValueError('Incomplete root overlay accounting')
        return paths
    raise ValueError('Root overlay unavailable')


class AllocatedBlocks:
    """Deduplicate hardlinks and shared layers/volumes by device and inode."""
    def __init__(self):
        self.seen = set()
        self.bytes = 0
        self.files = 0
        self.disappeared = 0

    def add_stat(self, stat):
        key = stat.st_dev, stat.st_ino
        if key not in self.seen:
            self.seen.add(key)
            self.bytes += stat.st_blocks * 512
            self.files += 1

    def add_tree(self, path):
        # Never follow workload-created symlinks into retained data or secrets.
        try:
            info = Path(path).lstat()
            if not stat_mode.S_ISDIR(info.st_mode):
                self.add_stat(info)
                return
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            self.disappeared += 1
            return
        self._directory(descriptor)

    def _directory(self, descriptor):
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) in self.seen:
                return
            self.add_stat(info)
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    try:
                        info = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                        if stat_mode.S_ISDIR(info.st_mode):
                            child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                            dir_fd=descriptor)
                            self._directory(child)
                        else:
                            self.add_stat(info)
                    except (FileNotFoundError, NotADirectoryError):
                        self.disappeared += 1
        finally:
            os.close(descriptor)


def image_files(digests, content, architecture):
    """Resolve locally resident OCI manifests; never inspect config contents."""
    pending = list(digests)
    seen = set()
    paths = set()
    missing = set()
    while pending:
        digest = pending.pop()
        if not DIGEST.fullmatch(digest):
            raise ValueError('Immutable image digest required')
        if digest in seen:
            continue
        seen.add(digest)
        path = content / digest.split(':')[1]
        if not path.is_file():
            missing.add(digest)
            continue
        paths.add(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Unexpectedly large image manifest')
        value = json.loads(path.read_text())
        if 'manifests' in value:
            matches = [entry for entry in value['manifests']
                       if entry.get('platform', {}).get('os') == 'linux'
                       and entry.get('platform', {}).get('architecture') == architecture]
            if len(matches) != 1:
                raise ValueError('Exactly one matching image platform required')
            pending.append(matches[0]['digest'])
        elif 'config' in value and 'layers' in value:
            for entry in [value['config'], *value['layers']]:
                if not DIGEST.fullmatch(entry['digest']):
                    raise ValueError('Invalid image content digest')
                blob = content / entry['digest'].split(':')[1]
                if blob.is_file():
                    paths.add(blob)
                else:
                    missing.add(entry['digest'])
        else:
            raise ValueError('Unrecognized OCI manifest')
    return paths, missing


def pod_cgroup(root, uid):
    """Resolve the host hierarchy, not namespace-relative /proc cgroup paths."""
    if not UUID.fullmatch(uid):
        raise ValueError('Pod UUID required')
    candidates = [root / 'kubepods' / ('pod' + uid)]
    escaped = uid.replace('-', '_')
    candidates.append(root / 'kubepods.slice' / ('kubepods-pod' + escaped + '.slice'))
    for qos in ('burstable', 'besteffort'):
        candidates += [root / 'kubepods' / qos / ('pod' + uid),
                       root / 'kubepods.slice' / ('kubepods-' + qos + '.slice') /
                       ('kubepods-' + qos + '-pod' + escaped + '.slice')]
    found = [path for path in candidates if path.is_dir()]
    if len(found) != 1:
        raise ValueError('Exactly one host Pod cgroup required')
    return found[0]


def sample(uid, namespace, name, images, architecture='amd64', host=Path('/host')):
    if not UUID.fullmatch(uid) or namespace != 'arc-runners' or not re.fullmatch(r'[a-z0-9-]+', name):
        raise ValueError('Exact disposable ARC Pod identity required')
    started = time.time()
    blocks = AllocatedBlocks()
    roots = set()
    pids = []
    failures = []
    proc = host / 'proc'
    uid_forms = (uid, uid.replace('-', '_'))
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            group = (entry / 'cgroup').read_text()
            lines = [line.removeprefix('0::') for line in group.splitlines()
                     if line.startswith('0::') and any('pod' + form in line for form in uid_forms)]
            if not lines:
                continue
            pids.append(entry)
            mounts = (entry / 'mountinfo').read_text()
            if (entry / 'cgroup').read_text() != group:
                failures.append('process-cgroup-changed-during-scan')
                continue
            roots.update(overlay_paths(mounts))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, ValueError) as error:
            failures.append(type(error).__name__)
    for root in sorted(roots):
        blocks.add_tree(host / root.lstrip('/'))
    # Shared emptyDirs, including nested Docker, are counted exactly once.
    volumes = host / 'var/lib/kubelet/pods' / uid / 'volumes/kubernetes.io~empty-dir'
    logs = host / 'var/log/pods' / (namespace + '_' + name + '_' + uid)
    for root in (volumes, logs):
        if root.exists():
            blocks.add_tree(root)
    # Files unlinked while still open continue to consume filesystem blocks.
    for pid in pids:
        try:
            if not any('pod' + form in (pid / 'cgroup').read_text() for form in uid_forms):
                continue
            for fd in (pid / 'fd').iterdir():
                try:
                    if os.readlink(fd).endswith(' (deleted)'):
                        blocks.add_stat(fd.stat())
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            failures.append('unreadable-open-files')
    content = host / 'var/lib/containerd/io.containerd.content.v1.content/blobs/sha256'
    blobs, missing = image_files(images, content, architecture)
    for blob in sorted(blobs):
        blocks.add_tree(blob)
    cpu = memory_peak = None
    try:
        directory = pod_cgroup(host / 'sys/fs/cgroup', uid)
        cpu = dict(line.split() for line in (directory / 'cpu.stat').read_text().splitlines())
        cpu = {key: int(value) for key, value in cpu.items()}
        memory_peak = int((directory / 'memory.peak').read_text())
    except (FileNotFoundError, ValueError):
        failures.append('pod-cgroup-unavailable')
    return {'pod_uid': uid, 'pod_name': name, 'sample_started': started,
            'sample_finished': time.time(), 'allocated_bytes': blocks.bytes,
            'unique_inodes': blocks.files, 'vanished_during_scan': blocks.disappeared,
            'root_overlay_paths': sorted(roots), 'processes_seen': len(pids),
            'cpu': cpu, 'memory_peak_bytes': memory_peak,
            'missing_image_blobs': sorted(missing), 'failures': failures,
            'qualification': 'sample-only; coverage and all container lifetimes must be verified'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--image', action='append', required=True)
    parser.add_argument('--architecture', choices=['amd64', 'arm64'], default='amd64')
    args = parser.parse_args()
    print(json.dumps(sample(args.uid, 'arc-runners', args.name, args.image, args.architecture)))
