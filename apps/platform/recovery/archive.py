"""Bounded full-volume capture and isolated restore; never follows archive links."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tarfile

VOLUMES = ('models', 'workspace', 'vector')
MAX_BYTES = 2 * 1024 ** 3
MAX_FILES = 100000


def inventory(root):
    result = {}
    total = 0
    for volume in VOLUMES:
        base = root / volume
        if not base.is_dir() or base.is_symlink():
            raise ValueError('Expected all three volume roots')
        device = base.stat().st_dev
        for current, directories, files in os.walk(base, followlinks=False):
            for name in sorted(directories + files):
                path = Path(current) / name
                info = path.lstat()
                relative = path.relative_to(root).as_posix()
                if info.st_dev != device or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError('Backup refuses links, special files and nested filesystems')
                if len(result) >= MAX_FILES:
                    raise ValueError('Backup file count exceeds reviewed bound')
                if stat.S_ISDIR(info.st_mode):
                    result[relative] = {'kind': 'directory', 'mode': stat.S_IMODE(info.st_mode) & 0o777}
                    continue
                total += info.st_size
                if total > MAX_BYTES:
                    raise ValueError('Backup exceeds reviewed two GiB restore bound')
                with path.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                result[relative] = {'kind': 'file', 'size': info.st_size, 'sha256': digest, 'mode': stat.S_IMODE(info.st_mode) & 0o777}
    return result


def capture(root, stream):
    manifest = inventory(root)
    import io
    data = json.dumps(manifest, sort_keys=True).encode()
    with tarfile.open(fileobj=stream, mode='w|gz') as archive:
        header = tarfile.TarInfo('manifest.json')
        header.size = len(data)
        archive.addfile(header, io.BytesIO(data))
        for name in sorted(manifest):
            archive.add(root / name, arcname=name, recursive=False)
    if manifest != inventory(root):
        raise ValueError('Volume contents changed during capture')


def restore(root, stream):
    if root.exists() and any(root.iterdir()):
        raise ValueError('Isolated restore requires an empty target')
    root.mkdir(parents=True, exist_ok=True)
    for volume in VOLUMES:
        (root / volume).mkdir()
    total = 0
    count = 0
    seen = set()
    manifest = None
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for member in archive:
            count += 1
            if count > MAX_FILES + 1:
                raise ValueError('Archive file count exceeds reviewed bound')
            name = member.name
            if (name in seen or name.startswith('/') or '..' in Path(name).parts
                    or name != Path(name).as_posix() or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe or duplicate archive entry')
            seen.add(name)
            if name == 'manifest.json':
                if manifest is not None or not member.isfile() or member.size > 32 * 1024 ** 2:
                    raise ValueError('Invalid archive manifest')
                manifest = json.load(archive.extractfile(member))
                continue
            if name.split('/')[0] not in VOLUMES or len(Path(name).parts) < 2:
                raise ValueError('Archive path outside application volumes')
            target = root / name
            total += member.size
            if total > MAX_BYTES:
                raise ValueError('Restore exceeds reviewed two GiB bound')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                with target.open('xb') as output:
                    shutil.copyfileobj(archive.extractfile(member), output)
    if not isinstance(manifest, dict):
        raise ValueError('Missing archive manifest')
    for name in sorted(seen - {'manifest.json'}, reverse=True):
        entry = manifest.get(name, {})
        mode = entry.get('mode')
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise ValueError('Invalid restored mode')
        (root / name).chmod(mode)
    actual = inventory(root)
    if manifest is None or manifest != actual:
        raise ValueError('Restored file inventory or content digest mismatch')
    databases = 0
    for name, entry in actual.items():
        if entry['kind'] != 'file':
            continue
        path = root / name
        with path.open('rb') as source:
            sqlite = source.read(16) == b'SQLite format 3\0'
        if sqlite:
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
                if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Restored SQLite integrity check failed')
            databases += 1
    return {'files': sum(v['kind'] == 'file' for v in actual.values()), 'bytes': total,
            'sqlite_databases': databases, 'inventory_sha256': hashlib.sha256(
                json.dumps(actual, sort_keys=True).encode()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'restore', 'inventory'))
    args = parser.parse_args()
    if args.operation == 'capture':
        capture(Path('/snapshot'), sys.stdout.buffer)
    elif args.operation == 'restore':
        print(json.dumps(restore(Path('/restore/data'), sys.stdin.buffer), sort_keys=True))
    else:
        data = inventory(Path('/snapshot'))
        print(json.dumps({'files': len(data), 'bytes': sum(v.get('size', 0) for v in data.values())}))
