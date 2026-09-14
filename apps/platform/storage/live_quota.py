"""Explicit maintenance only: bounded, fixed disposable project fixtures."""
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import struct
import sys

from collector import filesystem_uuid
from xfs import (PROJINHERIT, SET_ATTR, assign_empty_directory, get_quota,
                 open_mount, open_project, project_attributes, set_limit)

LIMIT = 2 * 1024**2
FIXTURES = (('ai-quota-proof-first', 31990), ('ai-quota-proof-neighbor', 31991))
FILES = {'run-id', 'persist', 'neighbor'}


def read_file(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        if os.fstat(fd).st_size > 128:
            raise ValueError('Unexpected fixture content')
        return os.read(fd, 129)
    finally:
        os.close(fd)


def create_file(directory, name, value):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory)
    try:
        os.write(fd, value)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory)


def headroom(mount):
    stat = os.fstatvfs(mount)
    if stat.f_bavail * stat.f_frsize < 32 * LIMIT:
        raise ValueError('Insufficient physical headroom for bounded disposable proof')


def admin(mount, phase, run_id):
    if phase not in ('prepare', 'verify', 'cleanup') or not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Fixed maintenance phase and run identity required')
    headroom(mount)
    for name, project in FIXTURES:
        directory = open_project(mount, name)
        try:
            if phase == 'prepare':
                if os.listdir(directory):
                    raise ValueError('An earlier fixture needs explicit recovery before reuse')
                try:
                    existing = get_quota(mount, project)
                except OSError as error:
                    if error.errno not in (errno.ENOENT, errno.ESRCH):
                        raise
                    existing = None
                if existing is not None and (existing.blocks or existing.inodes > 1):
                    raise ValueError('Reserved project identity already has data')
                assign_empty_directory(directory, project)
                set_limit(mount, project, LIMIT)
                os.fchown(directory, 0, 1000)
                os.fchmod(directory, 0o770)
                create_file(directory, 'run-id', run_id.encode())
            else:
                attrs = project_attributes(directory)
                if attrs[3] != project or not attrs[0] & PROJINHERIT or get_quota(mount, project).hard * 512 != LIMIT:
                    raise ValueError('Fixture quota or inheritance did not persist')
                if read_file(directory, 'run-id') != run_id.encode():
                    raise ValueError('Fixture belongs to a different maintenance run')
                if set(os.listdir(directory)) - FILES:
                    raise ValueError('Unexpected fixture files; refusing cleanup')
                if read_file(directory, 'persist') != run_id.encode():
                    raise ValueError('Consumer data did not persist')
                if project == FIXTURES[1][1] and read_file(directory, 'neighbor') != run_id.encode():
                    raise ValueError('Neighbor write was not verified')
                if phase == 'cleanup':
                    for filename in sorted(os.listdir(directory)):
                        if read_file(directory, filename) != run_id.encode():
                            raise ValueError('Unexpected fixture data; refusing cleanup')
                        os.unlink(filename, dir_fd=directory)
                    os.fsync(directory)
        finally:
            os.close(directory)
    print('PASS: fixed disposable quota fixtures ' + phase)


def consumer(run_id):
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Fixed maintenance identity required')
    maps = [list(map(int, line.split())) for line in Path('/proc/self/uid_map').read_text().splitlines()]
    if not maps or any(row[1] == 0 or row[2] > 65536 for row in maps):
        raise ValueError('Actual isolated Pod user namespace required')
    first = os.open('/first', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    neighbor = os.open('/neighbor', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for directory, (_, project) in zip((first, neighbor), FIXTURES):
            attrs = project_attributes(directory)
            if attrs[3] != project or not attrs[0] & PROJINHERIT or read_file(directory, 'run-id') != run_id.encode():
                raise ValueError('Unexpected consumer project identity')
            if 'persist' not in os.listdir(directory):
                create_file(directory, 'persist', run_id.encode())
            if read_file(directory, 'persist') != run_id.encode():
                raise ValueError('Data did not persist across consumer Pods')
        os.mkdir('owned-dir', mode=0o700, dir_fd=first)
        owned = os.open('owned-dir', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=first)
        try:
            attrs = list(project_attributes(owned))
            attrs[0] &= ~PROJINHERIT
            try:
                fcntl.ioctl(owned, SET_ATTR, struct.pack('=IIIII8s', *attrs))
            except OSError as error:
                if error.errno not in (errno.EPERM, errno.EINVAL):
                    raise
            else:
                raise ValueError('Application directory owner disabled project inheritance')
            if not project_attributes(owned)[0] & PROJINHERIT:
                raise ValueError('Project inheritance changed')
        finally:
            os.close(owned)
            os.rmdir('owned-dir', dir_fd=first)
        fd = os.open('proof', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=first)
        try:
            if os.fstat(fd).st_uid != os.geteuid():
                raise ValueError('Expected an application-owned file')
            attrs = list(project_attributes(fd))
            attrs[3] = 0
            try:
                fcntl.ioctl(fd, SET_ATTR, struct.pack('=IIIII8s', *attrs))
            except OSError as error:
                if error.errno not in (errno.EPERM, errno.EINVAL):
                    raise
            else:
                raise ValueError('Application file owner escaped to project zero')
            if project_attributes(fd)[3] != FIXTURES[0][1]:
                raise ValueError('Project identity changed')
            rejected = False
            try:
                for _ in range(160):  # At most 10 MiB even if enforcement is broken.
                    os.write(fd, bytes(65536))
                os.fsync(fd)
            except OSError as error:
                if error.errno not in (errno.EDQUOT, errno.ENOSPC):
                    raise
                rejected = True
            if not rejected:
                raise ValueError('Kernel did not enforce the disposable hard limit')
            if 'neighbor' not in os.listdir(neighbor):
                create_file(neighbor, 'neighbor', run_id.encode())
            else:
                # Prove a fresh neighboring write on every consumer invocation.
                create_file(neighbor, 'neighbor-check', run_id.encode())
                os.unlink('neighbor-check', dir_fd=neighbor)
                os.fsync(neighbor)
        finally:
            os.close(fd)
            os.unlink('proof', dir_fd=first)
            os.fsync(first)
    finally:
        os.close(first)
        os.close(neighbor)
    print('PASS: actual user-namespaced consumer, project-zero rejection, hard-limit rejection, neighbor write and persistent data')


def main(phase, run_id):
    if phase == 'consumer':
        consumer(run_id)
    else:
        config = json.loads(Path('/config/config.json').read_text())
        mount = open_mount('/var/mnt/local-path-provisioner', '/dev/sdb1')
        try:
            if filesystem_uuid(mount) != config['filesystemUUID']:
                raise ValueError('Unexpected worker filesystem identity')
            admin(mount, phase, run_id)
        finally:
            os.close(mount)


if __name__ == '__main__':
    main(*sys.argv[1:])
