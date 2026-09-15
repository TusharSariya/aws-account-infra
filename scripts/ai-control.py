#!/usr/bin/env python3
"""Use the private authenticated lifecycle API with an explicit command revision."""
import argparse
import json
from pathlib import Path
import re
from lifecycle_session import apps
import uuid

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('status', 'start', 'stop', 'force-stop'))
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--revision', type=int)
    parser.add_argument('--command-id')
    args = parser.parse_args()
    if args.credentials.stat().st_mode & 0o077:
        parser.error('Credential file must be private to its owner')
    token = json.loads(args.credentials.read_text())['operator']
    payload = None
    if args.operation != 'status':
        if args.revision is None:
            parser.error('Read Status and pass its revision for a new operation')
        command = args.command_id or str(uuid.uuid4())
        if str(uuid.UUID(command)) != command:
            parser.error('Canonical UUID command ID required')
        payload = {'command_id': command, 'revision': args.revision}
        print(json.dumps({'operation': args.operation, **payload}), flush=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise ValueError('Invalid operator credential')
    config = 'header = "Authorization: Bearer ' + token + '"\n'
    options = ['--fail-with-body', '--config', '-']
    if payload is not None:
        config += 'header = "Content-Type: application/json"\n'
        options += ['--data-binary', json.dumps(payload)]
    # Resolve the exact Tailscale peer while retaining hostname/SNI and TLS checks.
    # Credentials travel on stdin; curl follows no redirects by default.
    response = apps.tailnet_https('ai-lifecycle.tail2f646b.ts.net', '/' + args.operation,
                                 options, config.encode())
    print(json.dumps(json.loads(response), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError):
        raise SystemExit('Operation unavailable or rejected. Inspect Status; retry an ambiguous request only with its original command ID and revision.') from None
