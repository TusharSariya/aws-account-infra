"""Assert an application file owner cannot escape its project from a user namespace."""
import errno
import fcntl
import os
import struct
import subprocess
import sys
sys.path.insert(0, '/source/apps/platform/storage')
from xfs import SET_ATTR, PROJINHERIT, project_attributes


def attempt(fd):
    file_fd = os.open('user-owned', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        assert os.fstat(file_fd).st_uid == os.geteuid()
        for target, field, value in [(file_fd, 3, 0),
                                     (fd, 0, project_attributes(fd)[0] & ~PROJINHERIT)]:
            attrs = list(project_attributes(target))
            attrs[field] = value
            try:
                fcntl.ioctl(target, SET_ATTR, struct.pack('=IIIII8s', *attrs))
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
    # Container runtimes create Pod user namespaces as the host administrator.
    # Do the same here: Ubuntu runners restrict unprivileged uid_map creation.
    # The adversarial process is root *inside* the new namespace, a stronger
    # attacker than the non-root application, but cannot administer host quotas.
    subprocess.run(['unshare', '--user', '--map-root-user', sys.executable, __file__,
                    str(directory_fd), os.readlink('/proc/self/ns/user')],
                   pass_fds=(directory_fd,), check=True, timeout=20)
    print('PASS: user-namespace file owner cannot change project ID to zero')


if __name__ == '__main__':
    assert os.readlink('/proc/self/ns/user') != sys.argv[2]
    attempt(int(sys.argv[1]))
