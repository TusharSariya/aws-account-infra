#!/usr/bin/env python3
"""Issue a 30-minute namespace-scoped Argo client token into a new private file."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    # Existing private kubeconfig and checksum-verified kubectl are prerequisites.
    kubectl = Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'
    descriptor = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        result = subprocess.run([str(kubectl), '--request-timeout=20s', '-n', 'homelab-jobs',
            'create', 'token', 'homelab-workflow-client', '--duration=30m'], capture_output=True, timeout=30, check=True)
        token = result.stdout.strip()
        if token.count(b'.') != 2 or len(token) < 100:
            raise ValueError('Token response invalid')
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = None
            output.write(token + b'\n')
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        args.destination.unlink(missing_ok=True)
        raise
    print('Private namespace-scoped client token issued for 30 minutes; no credential printed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit('Client-token issuance failed; verify existing private Kubernetes access.') from None
