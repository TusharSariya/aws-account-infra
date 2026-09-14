"""Run only on the disposable XFS mount created by quota-linux.sh."""
import os
import sys
sys.path.insert(0, '/source/apps/platform/storage')
from xfs import assign_empty_directory, get_quota, open_mount, open_project, prove_enforcement, set_limit

from collector import filesystem_uuid
from project_identity import verify
from live_quota import admin, FIXTURES, create_file

mount = open_mount('/quota-test', sys.argv[1])
try:
    assert filesystem_uuid(mount) == sys.argv[2]
    proof_id = '1' * 32
    admin(mount, 'prepare', proof_id)
    for name, _ in FIXTURES:
        directory = open_project(mount, name)
        try:
            create_file(directory, 'persist', proof_id.encode())
            if name.endswith('neighbor'):
                create_file(directory, 'neighbor', proof_id.encode())
        finally:
            os.close(directory)
    admin(mount, 'verify', proof_id)
    admin(mount, 'cleanup', proof_id)
    first = open_project(mount, 'ai-test-first')
    second = open_project(mount, 'ai-test-second')
    try:
        for fd, project in [(first, 62001), (second, 62002)]:
            assign_empty_directory(fd, project)
            assign_empty_directory(fd, project)
            set_limit(mount, project, 2 * 1024**2)
        prove_enforcement(mount, first, 2 * 1024**2)
        fd = os.open('neighbor', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=second)
        try:
            os.write(fd, b'neighbor remains writable')
            os.fsync(fd)
        finally:
            os.close(fd)
        assert get_quota(mount, 62002).blocks > 0
        verify(second)
        # Exceed declarations, never physical usage.
        set_limit(mount, 62001, 10 * 1024**3)
        set_limit(mount, 62002, 10 * 1024**3)
        assert get_quota(mount, 62001).hard * 512 == 10 * 1024**3
        print('PASS: kernel quota rejection, independent neighbor write, idempotence and overcommit')
    finally:
        os.close(first)
        os.close(second)
finally:
    os.close(mount)
