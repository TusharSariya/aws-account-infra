#!/usr/bin/env python3
"""Prepare only pinned upstream source and explicit packaging inputs for GHCR."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'apps/containers/odysseus'


def prepare(destination):
    lock = json.loads((PACKAGE / 'source.lock.json').read_text())
    data = urllib.request.urlopen(lock['archive_url'], timeout=120).read()
    if hashlib.sha256(data).hexdigest() != lock['archive_sha256']:
        raise ValueError('Upstream source checksum mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        archive.extractall(destination, filter='data')
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('Expected one upstream source directory')
    source = roots[0]
    dockerfile = (source / 'Dockerfile').read_text()
    if dockerfile.count('FROM python:3.14-slim') != 2:
        raise ValueError('Upstream Dockerfile changed; review base image pinning')
    # The CPU workspace does not ship the optional Real-ESRGAN GPU wheel builder.
    # Its isolated build dependencies otherwise install several GB of CUDA/torch.
    dockerfile = 'FROM python:3.14-slim' + dockerfile.split('FROM python:3.14-slim', 2)[2]
    start = dockerfile.index('# Pre-install the patched basicsr/')
    end = dockerfile.index('# Copy app code', start)
    dockerfile = dockerfile[:start] + dockerfile[end:]
    # Host Docker management is deliberately absent from this Kubernetes service.
    start = dockerfile.index('# Docker CLI (client only')
    end = dockerfile.index('WORKDIR /app', start)
    dockerfile = dockerfile[:start] + dockerfile[end:]
    dockerfile = dockerfile.replace('ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]', '')
    dockerfile = dockerfile.replace('FROM python:3.14-slim', 'FROM ' + lock['python_image'])
    dockerfile = 'FROM ' + lock['ollama_image'] + ' AS ollama-client\n' + dockerfile
    dockerfile += (PACKAGE / 'Dockerfile.append').read_text()
    (source / 'Dockerfile').write_text(dockerfile)
    shutil.copyfile(PACKAGE / 'entrypoint.sh', source / 'homelab-entrypoint.sh')
    shutil.copyfile(PACKAGE / 'source.lock.json', source / 'homelab-source.lock.json')
    print(source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
