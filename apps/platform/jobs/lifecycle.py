"""A reviewed operation issues exactly one revision-fenced command, then observes."""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = 'http://ai-lifecycle.homelab-platform.svc:8080'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(path, payload=None):
    token = Path('/credentials/operator').read_text().strip()
    request = urllib.request.Request(BASE + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(request, timeout=10) as response:
        return json.load(response)


def main():
    action = os.environ['OPERATION']
    if action not in ('start', 'stop', 'force-stop', 'status'):
        raise ValueError('Unreviewed operation')
    if action == 'status':
        print(json.dumps(call('/status')))
        return
    payload = {'command_id': os.environ['COMMAND_ID'], 'revision': int(os.environ['COMMAND_REVISION'])}
    result = call('/' + action, payload)
    revision = result['acknowledged_revision']
    print(json.dumps(result), flush=True)
    target = 'On' if action == 'start' else 'Off'
    # Cancellation cancels observation, not a previously committed command.
    # Stop and Force Stop must always remain explicit subsequent operations.
    while result['observed'] != target:
        time.sleep(3)
        result = call('/status')
        if result['revision'] != revision:
            raise RuntimeError('Operation superseded; inspect current Status')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError):
        raise SystemExit('Operation unavailable, rejected or superseded; inspect authenticated Status before issuing another command') from None
