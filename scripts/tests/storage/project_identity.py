"""Assert an application file owner cannot escape its project from a user namespace."""
import errno
import fcntl
import os
import struct
import subprocess
import sys
sys.path.insert(0, '/source/apps/platform/storage')
from xfs import SET_ATTR, project_attributes


def attempt(fd):
    file_fd = os.open('user-owned', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        attrs = list(project_attributes(file_fd))
        attrs[3] = 0
        try:
            fcntl.ioctl(file_fd, SET_ATTR, struct.pack('=IIIII8s', *attrs))
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EINVAL):
                raise
        else:
            raise AssertionError('Application escaped its project hard limit')
    finally:
        os.close(file_fd)
        os.unlink('user-owned', dir_fd=fd)


def verify(directory_fd):
    os.fchown(directory_fd, 0, 1000)
    os.fchmod(directory_fd, 0o770)
    def drop_identity():
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    subprocess.run(['unshare', '--user', '--map-root-user', sys.executable, __file__, str(directory_fd)],
                   pass_fds=(directory_fd,), preexec_fn=drop_identity, check=True, timeout=20)
    print('PASS: user-namespace file owner cannot change project ID to zero')


if __name__ == '__main__':
    attempt(int(sys.argv[1]))
