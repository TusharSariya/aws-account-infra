#!/usr/bin/env python3
"""Temporary read-only schema transport diagnosis; never prints API payloads."""
import os
from pathlib import Path
import subprocess
import sys


def probe(kubectl, kubeconfig):
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': os.environ['HOME'],
           'KUBECONFIG': str(kubeconfig)}
    for name, flags in [('vip-compressed', []),
                        ('vip-uncompressed', ['--disable-compression']),
                        ('control-plane-compressed', ['--server=https://10.42.0.220:6443'])]:
        command = [str(kubectl), '--request-timeout=15s', 'get', '--raw=/openapi/v2', *flags]
        try:
            result = subprocess.run(command, env=env, capture_output=True, timeout=20)
            status = 'success' if result.returncode == 0 else 'failure'
            size = len(result.stdout) if result.returncode == 0 else 0
        except subprocess.TimeoutExpired:
            status, size = 'timeout', 0
        print(f'[DEBUG-schema-transport] {name}: {status}; bytes={size}', flush=True)


if __name__ == '__main__':
    probe(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3', Path(sys.argv[1]) / 'kubeconfig')
