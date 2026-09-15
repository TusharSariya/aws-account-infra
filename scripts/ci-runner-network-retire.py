#!/usr/bin/env python3
"""Remove only the exact retired VM 103 DHCP reservation on the existing router."""
import os
from pathlib import Path
import subprocess


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run on the existing router as root')
    target = Path('/etc/NetworkManager/dnsmasq-shared.d/ci-runner.conf')
    expected = 'dhcp-host=02:42:00:00:01:05,10.42.0.225,ci-runner-01,infinite\n'
    if not target.exists():
        print('CI reservation already absent')
        return
    if target.is_symlink() or target.read_text() != expected:
        raise SystemExit('CI reservation differs; refusing to modify router configuration')
    # Retain original bytes in an exclusive private backup, outside the active conf-dir.
    backup = Path('/root/ci-runner-retired-dhcp.conf')
    if backup.exists() and backup.read_text() != expected:
        raise SystemExit('Retirement backup differs')
    if not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(expected)
    target.unlink()
    print('Exact CI reservation removed. Activate through reviewed router maintenance and verify Pi-hole.')

if __name__ == '__main__':
    main()
