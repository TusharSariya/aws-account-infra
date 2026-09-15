#!/usr/bin/env python3
"""Issue independent lifecycle credentials into a new private local directory."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets


def issue(destination):
    os.umask(0o077)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    values = {name: secrets.token_urlsafe(32) for name in ('operator', 'odysseus', 'ollama', 'model-user', 'model-workspace')}
    (destination / 'credentials.json').write_text(json.dumps(values) + '\n')
    (destination / 'github-secret.b64').write_bytes(base64.b64encode(json.dumps(values).encode()))
    print('Created five independent credentials in the private destination; values are not printed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    issue(parser.parse_args().destination)
