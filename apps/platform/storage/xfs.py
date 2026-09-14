"""Linux XFS quota operations via file descriptors; no host devices or shell.

ABI: Linux include/uapi/linux/dqblk_xfs.h and include/uapi/linux/fs.h.
Only project block limits are changed. No quota disabling, deletion or remount.
"""
import ctypes
import errno
import fcntl
import os
import platform
from pathlib import Path
import struct

GET_ATTR = 0x801c581f
SET_ATTR = 0x401c5820
PROJINHERIT = 0x200
PROJECT = 2


class DiskQuota(ctypes.Structure):
    _fields_ = [('version', ctypes.c_int8), ('flags', ctypes.c_int8),
                ('fieldmask', ctypes.c_uint16), ('id', ctypes.c_uint32),
                ('hard', ctypes.c_uint64), ('soft', ctypes.c_uint64),
                ('ihard', ctypes.c_uint64), ('isoft', ctypes.c_uint64),
                ('blocks', ctypes.c_uint64), ('inodes', ctypes.c_uint64),
                ('tail', ctypes.c_byte * 56)]


def quota(fd, command, project, buffer):
    libc = ctypes.CDLL(None, use_errno=True)
    # glibc does not export quotactl_fd. Linux assigns syscall 443 on both
    # supported 64-bit architectures; reject other ABIs explicitly.
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise ValueError('Supported Linux 64-bit ABI required')
    call = libc.syscall
    call.restype = ctypes.c_long
    if call(ctypes.c_long(443), ctypes.c_int(fd),
            ctypes.c_uint(((ord('X') << 8 | command) << 8) | PROJECT),
            ctypes.c_uint(project), ctypes.byref(buffer)):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return buffer


def enforcement(fd):
    # Versioned quota status is 160 bytes on Linux's 64-bit ABI; reserve extra
    # zeroed space and read only the documented version and flag prefix.
    data = ctypes.create_string_buffer(256)
    data[0] = b'\x01'
    quota(fd, 8, 0, data)
    flags = struct.unpack_from('=H', data.raw, 2)[0]
    if flags & 0x30 != 0x30:
        raise ValueError('XFS project accounting AND enforcement must be enabled')


def get_quota(fd, project):
    return quota(fd, 3, project, DiskQuota())


def set_limit(fd, project, limit):
    if type(project) is not int or not 1 <= project < 2**32:
        raise ValueError('Nonzero project ID required')
    if type(limit) is not int or limit <= 0 or limit % 512:
        raise ValueError('Positive 512-byte-aligned hard limit required')
    data = DiskQuota(version=1, flags=2, fieldmask=12, id=project, hard=limit // 512)
    quota(fd, 4, project, data)
    result = get_quota(fd, project)
    if result.hard * 512 != limit:
        raise ValueError('Kernel hard limit differs from requested limit')


def project_attributes(fd):
    return struct.unpack('=IIIII8s', fcntl.ioctl(fd, GET_ATTR, bytes(28)))


def assign_empty_directory(fd, project):
    """Only initialize empty new directories; never relabel existing data."""
    attrs = list(project_attributes(fd))
    if attrs[3] == project and attrs[0] & PROJINHERIT:
        return
    if attrs[3] != 0 or os.listdir(fd):
        raise ValueError('Refusing to relabel an occupied or foreign project directory')
    attrs[0] |= PROJINHERIT
    attrs[3] = project
    fcntl.ioctl(fd, SET_ATTR, struct.pack('=IIIII8s', *attrs))
    observed = project_attributes(fd)
    if observed[3] != project or not observed[0] & PROJINHERIT:
        raise ValueError('Project inheritance did not persist')


def open_mount(path, source):
    """Require exact XFS mount, never silently write to its parent filesystem."""
    path = Path(path)
    if str(path.resolve()) != str(path):
        raise ValueError('Mount path must be absolute with no symlinks')
    matches = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields, fs = left.split(), right.split()
        if fields[4] == str(path):
            matches.append((fields, fs))
    if len(matches) != 1:
        raise ValueError('Expected one exact mount')
    fields, fs = matches[0]
    if fields[3] != '/' or fs[0] != 'xfs' or fs[1] != source or 'rw' not in fields[5].split(','):
        raise ValueError('Unexpected mount root, filesystem, source or access mode')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        enforcement(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_project(mount_fd, name):
    if not name.startswith('ai-') or '/' in name or '\\' in name or name in ('.', '..'):
        raise ValueError('Invalid project basename')
    try:
        os.mkdir(name, mode=0o750, dir_fd=mount_fd)
    except FileExistsError:
        pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=mount_fd)
    if os.fstat(fd).st_dev != os.fstat(mount_fd).st_dev:
        os.close(fd)
        raise ValueError('Project must use the expected filesystem')
    return fd


def prove_enforcement(mount_fd, directory_fd, limit):
    """Only for disposable, small isolated test projects, never production data."""
    if not 0 < limit <= 8 * 1024**2:
        raise ValueError('Disposable test limit must be at most 8 MiB')
    space = os.fstatvfs(mount_fd)
    if space.f_bavail * space.f_frsize < 16 * limit:
        raise ValueError('Insufficient physical headroom for isolated quota proof')
    name = 'enforcement-proof'
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        try:
            for _ in range(limit // 65536 + 128):
                os.write(fd, bytes(65536))
            os.fsync(fd)
        except OSError as error:
            if error.errno in (errno.EDQUOT, errno.ENOSPC):
                # XFS project limits can report ENOSPC. Require physical
                # headroom, plus the independent neighbor-write test.
                after = os.fstatvfs(mount_fd)
                if after.f_bavail * after.f_frsize < 8 * limit:
                    raise ValueError('Physical exhaustion is not quota proof')
                return
            raise
        raise ValueError('Quota did not reject excess writes with a quota-related error')
    finally:
        os.close(fd)
        os.unlink(name, dir_fd=directory_fd)
