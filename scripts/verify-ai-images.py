#!/usr/bin/env python3
"""Verify reviewed AI image digests correspond to unchanged inputs and successful CI."""
import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/environments/kubernetes/homelab'


class ImageError(ValueError):
    pass


def input_hash(name):
    paths = [path for path in (ROOT / 'apps/containers' / name).rglob('*')
             if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc']
    paths += [ROOT / 'scripts' / (name + '-image-context.py'), ROOT / 'scripts' / (name + '-image-smoke.sh'),
              ROOT / '.github/workflows' / (name + '-image.yml'), ROOT / 'scripts/verify-ai-images.py', ROOT / 'scripts/cache_download.py', ROOT / 'scripts/build_cache.py']
    if name == 'odysseus':
        paths.extend([ROOT / 'scripts/odysseus-smoke-controller.py', ROOT / 'scripts/odysseus-source-tests.py'])
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


API = 'https://api.github.com/repos/TusharSariyaOrg/aws-account-infra/actions/'


def api_json(path, token):
    request = urllib.request.Request(API + path, headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def artifact_receipt(artifact, token):
    request = urllib.request.Request(API + 'artifacts/' + str(artifact['id']) + '/zip',
                                     headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect()).open(request, timeout=15)
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise
        location = error.headers.get('Location', '')
    else:
        raise ImageError('Build receipt download did not return its expected redirect')
    if not location.startswith('https://'):
        raise ImageError('Build receipt requires a secure download')
    # The signed storage URL must never receive the GitHub credential.
    with urllib.request.urlopen(location, timeout=30) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ImageError('Build receipt artifact exceeds its size bound')
    if artifact.get('digest') != 'sha256:' + hashlib.sha256(payload).hexdigest():
        raise ImageError('Build receipt artifact checksum does not match GitHub metadata')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != 'receipt.json' or members[0].file_size > 65536:
            raise ImageError('Build receipt artifact has unexpected contents')
        return json.loads(archive.read(members[0]))


def receipt(name, image, commit, run_id):
    if not re.fullmatch('ghcr.io/tusharsariyaorg/homelab-' + name + r'@sha256:[0-9a-f]{64}', image):
        raise ImageError('Build receipt requires an immutable image digest')
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or run_id <= 0:
        raise ImageError('Build receipt requires a source commit and CI run')
    return {'image': image, 'commit': commit, 'run_id': run_id, 'input_sha256': input_hash(name)}


def verify_remote(name, record, token):
    run = api_json('runs/' + str(record['run_id']), token)
    if (run['status'] != 'completed' or run['conclusion'] != 'success' or run['head_sha'] != record['commit']
            or run['path'] != '.github/workflows/' + name + '-image.yml'):
        raise ImageError('Selected AI image build did not pass its required CI workflow')
    artifact = api_json('artifacts/' + str(record['artifact_id']), token)
    if (artifact['expired'] or artifact['name'] != name + '-image-receipt'
            or artifact['workflow_run']['id'] != record['run_id']
            or artifact['workflow_run']['head_sha'] != record['commit']):
        raise ImageError('Selected AI image receipt is expired or belongs to another build')
    expected = {key: record[key] for key in ('image', 'commit', 'run_id', 'input_sha256')}
    if artifact_receipt(artifact, token) != expected:
        raise ImageError('Selected AI image and source inputs do not match the successful build receipt')


def verify(images, remote=False):
    try:
        records = json.loads((CONFIG / 'ai-image-releases.json').read_text())
        for name in ('ollama', 'odysseus'):
            record = records[name]
            if images[name] != record['image'] or input_hash(name) != record['input_sha256']:
                raise ImageError('AI image inputs changed; a successful reviewed image build must be selected')
            if remote:
                token = os.environ.get('GH_TOKEN', '')
                if not token or type(record['run_id']) is not int:
                    raise ImageError('CI image verification requires authenticated run metadata')
                if type(record['artifact_id']) is not int:
                    raise ImageError('CI image verification requires a build artifact')
                verify_remote(name, record, token)
    except ImageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        raise ImageError('Reviewed AI image deployment evidence is missing or unavailable') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=('ollama', 'odysseus'))
    parser.add_argument('image')
    parser.add_argument('commit')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(receipt(args.name, args.image, args.commit,
                                           int(os.environ['GITHUB_RUN_ID'])), sort_keys=True) + '\n')
