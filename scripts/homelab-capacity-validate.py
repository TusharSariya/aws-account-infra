#!/usr/bin/env python3
"""Read-only live telemetry acceptance; never starts AI or changes storage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
from collector import healthy_sample


def main():
    values = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml').read_text())
    if not values['enabled']:
        print('PASS: capacity activation explicitly disabled; no live telemetry claim')
        return
    kubectl = os.environ['KUBECTL']
    for mode in ('guest', 'physical'):
        result = subprocess.run([kubectl, '--request-timeout=30s', '-n', 'homelab-platform',
            'get', 'configmap', mode + '-capacity', '-o', 'json'], capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise ValueError('Missing capacity report')
        sample = json.loads(json.loads(result.stdout)['data']['sample.json'])
        if not healthy_sample(mode, values['config'], sample, time.time()):
            raise ValueError('Unhealthy capacity report')
    print('PASS: both independent capacity reports have expected identities and fresh healthy measurements')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('ACCEPTANCE_DIAGNOSTIC: capacity line 1', file=sys.stderr)
        sys.exit(1)
