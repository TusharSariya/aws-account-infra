#!/usr/bin/env python3
"""Idempotent CI DHCP reservation on the existing NetworkManager router; syntax-check first."""
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root required on the existing DHCP router')
    root = Path('/etc/NetworkManager/dnsmasq-shared.d')
    target = root / 'ci-runner.conf'
    value = 'dhcp-host=02:42:00:00:01:05,10.42.0.225,ci-runner-01,infinite\n'
    if not (root / 'homelab-guests.conf').is_file():
        raise SystemExit('Existing homelab router configuration required')
    for path in root.glob('*'):
        if path.is_file() and path != target:
            for line in path.read_text().splitlines():
                if not line.strip().startswith('#') and ('10.42.0.225' in line or '02:42:00:00:01:05' in line):
                    raise SystemExit('Conflicting CI identity in existing router configuration')
    if target.exists():
        if target.read_text() != value:
            raise SystemExit('Existing CI reservation differs')
        return
    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / 'candidate.conf'
        candidate.write_text('conf-dir=' + str(root) + '\n' + value)
        subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(candidate)], check=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(value)
    print('Reservation written. Activate through the existing reviewed NetworkManager connection maintenance procedure.')


if __name__ == '__main__':
    main()
