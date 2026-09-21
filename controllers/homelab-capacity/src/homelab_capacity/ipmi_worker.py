"""Isolated pyghmi operation: no reset, boot, off, or arbitrary raw commands."""
import json
from pathlib import Path
import sys
from pyghmi.ipmi.command import Command


def execute(config_path, target, action):
    if action not in ('status', 'on'):
        raise ValueError('Operation not allowed')
    cfg = json.loads(Path(config_path).read_text())
    host = cfg['hosts'][target]
    secret_path = Path(host['password_file']).expanduser()
    if secret_path.stat().st_mode & 0o077:
        raise PermissionError('Credential file must not be accessible to group or others')
    secret = json.loads(secret_path.read_text())
    conn = Command(bmc=host['address'], userid=host['username'],
                   password=secret['password'], privlevel=3, keepalive=False)
    try:
        return conn.get_power() if action == 'status' else conn.set_power('on', wait=False)
    finally:
        conn.ipmi_session.logout()


if __name__ == '__main__':
    try:
        print(json.dumps(execute(*sys.argv[1:])))
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__}))
        sys.exit(1)
