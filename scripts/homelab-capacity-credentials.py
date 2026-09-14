#!/usr/bin/env python3
"""Reconcile only the independent collector Secret, outside OpenTofu state."""
import base64
import json
import os
import subprocess
import sys


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Reviewed main CI required')
    values = json.loads(base64.b64decode(os.environ['CAPACITY_CLIENT_CREDENTIALS_B64'], validate=True))
    if set(values) != {'ca.crt', 'tls.crt', 'tls.key'} or any(not isinstance(v, str) or not v for v in values.values()):
        raise ValueError('Exact collector credential bundle required')
    manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': 'physical-capacity-client', 'namespace': 'homelab-platform'},
                'data': {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}}
    env = {key: value for key, value in os.environ.items() if key != 'CAPACITY_CLIENT_CREDENTIALS_B64'}
    result = subprocess.run([os.environ['KUBECTL'], '--request-timeout=30s', 'apply', '--server-side',
        '--field-manager=homelab-capacity-credentials', '-f', '-'], input=json.dumps(manifest),
        text=True, capture_output=True, env=env, timeout=40)
    if result.returncode:
        raise ValueError('Credential reconciliation failed')
    print('PASS: independent capacity client Secret reconciled without OpenTofu state')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Capacity credential reconciliation failed; private output suppressed', file=sys.stderr)
        sys.exit(1)
