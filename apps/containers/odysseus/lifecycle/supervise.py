"""Unprivileged Linux subreaper: retain a command's lifetime through orphaned children."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def descendants():
    parents = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            text = (entry / 'stat').read_text()
            parents[int(entry.name)] = int(text[text.rfind(')') + 2:].split()[1])
        except FileNotFoundError:
            pass
    family = {os.getpid()}
    while True:
        added = {pid for pid, parent in parents.items() if parent in family}
        if added <= family:
            return family - {os.getpid()}
        family |= added


def main():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, no capability needed.
        raise RuntimeError('Subprocess lifetime supervision unavailable')
    requested = [None]
    def receive(signum, frame):
        requested[0] = signal.SIGKILL if signum == signal.SIGUSR1 else signum
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
        signal.signal(signum, receive)
    ready_fd = int(os.environ.pop('HOMELAB_SUPERVISOR_READY_FD'))
    os.write(ready_fd, b'R')
    os.close(ready_fd)
    spec = json.loads(sys.argv[1])
    child = subprocess.Popen(spec['args'], executable=spec.get('executable'), close_fds=False)
    original_status = None
    while True:
        if requested[0] is not None:
            for pid in descendants():
                try:
                    os.kill(pid, requested[0])
                except ProcessLookupError:
                    pass
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break  # Kernel confirms there are no children or adopted descendants.
        except InterruptedError:
            continue
        if pid == child.pid:
            original_status = os.waitstatus_to_exitcode(status)
            child.returncode = original_status
        if pid == 0:
            time.sleep(0.02)
    if requested[0] is not None:
        return 128 + requested[0]
    if original_status is None:
        return 125
    return original_status if original_status >= 0 else 128 - original_status


if __name__ == '__main__':
    sys.exit(main())
