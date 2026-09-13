#!/usr/bin/env python3
"""Publish the existing Talos secret bundle to GitHub prod without printing it."""
import base64
import hashlib
import json
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
source = Path.home() / '.config/aws-account-infra/talos/homelab/talos-secrets.yaml'
if source.is_symlink() or source.stat().st_uid != os.getuid() or source.stat().st_mode & 0o077:
    raise SystemExit('Expected an owned private cluster-secrets file')
bundle = source.read_bytes()
identity = json.loads((root / 'config/environments/talos/homelab/identity.json').read_text())
if hashlib.sha256(bundle).hexdigest() != identity['secrets_sha256']:
    raise SystemExit('Existing cluster identity fingerprint mismatch')
result = subprocess.run(['gh', 'secret', 'set', 'TALOS_SECRETS_B64', '--env', 'prod',
                         '--repo', 'TusharSariyaOrg/aws-account-infra'],
                        input=base64.b64encode(bundle), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if result.returncode:
    raise SystemExit('GitHub secret update failed; no secret output was printed')
print('Updated GitHub prod TALOS_SECRETS_B64 from the existing private bundle')
