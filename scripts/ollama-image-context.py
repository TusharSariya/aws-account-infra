#!/usr/bin/env python3
"""Prepare checksum-pinned Ollama plus reviewed admission/activity hooks."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'apps/containers/ollama'


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
    shutil.copytree(PACKAGE / 'lifecycle', source / 'lifecycle')
    shutil.copytree(PACKAGE / 'patcher', source / 'homelab-patcher')
    dockerfile = f'''FROM {lock['go_image']} AS build
WORKDIR /src
COPY . .
RUN go run ./homelab-patcher /src
RUN go test ./lifecycle ./api ./server ./llm
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w -X github.com/ollama/ollama/version.Version=0.34.0-homelab" -o /out/ollama .
FROM {lock['runtime_image']}
COPY --from=build /out/ollama /bin/ollama
ENV OLLAMA_NOPRUNE=true OLLAMA_NO_CLOUD=true
'''
    (source / 'Dockerfile').write_text(dockerfile)
    print(source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
