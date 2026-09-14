"""Single-use reset of three pinned legacy AI volumes. Never a routine controller."""
import json
import os
from pathlib import Path
import stat
import time
import urllib.request
import ssl

from collector import filesystem_uuid
from xfs import open_mount, project_attributes, get_quota, PROJINHERIT
from workload_state import is_terminated

CLAIMS = {'ollama-models': ('ai-models', 31001, 300 * 1024**3),
          'odysseus-data': ('ai-workspace', 31002, 20 * 1024**3),
          'chromadb-data': ('ai-vector', 31003, 10 * 1024**3)}
RECORD = '/api/v1/namespaces/homelab-platform/configmaps/ai-volume-reset-v1'


def api(path, method='GET', data=None):
    context = ssl.create_default_context(cafile='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt')
    token = Path('/var/run/secrets/kubernetes.io/serviceaccount/token').read_text().strip()
    host = os.environ['KUBERNETES_SERVICE_HOST']
    port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    request = urllib.request.Request(f'https://{host}:{port}' + path, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json-patch+json'},
        data=None if data is None else json.dumps(data).encode())
    with urllib.request.urlopen(request, context=context, timeout=15) as response:
        return json.load(response)


def transition(record, phase):
    return api(RECORD, 'PATCH', [
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': record['metadata']['resourceVersion']},
        {'op': 'replace', 'path': '/metadata/annotations/homelab~1reset-phase', 'value': phase},
        {'op': 'add', 'path': '/metadata/annotations/homelab~1reset-updated', 'value': str(time.time())}])


def validate_receipt(receipt):
    if set(receipt['claims']) != set(CLAIMS):
        raise ValueError('Exactly the three authorized AI claims are required')
    for field in ('claim_uid', 'pv_uid', 'pv_name'):
        if len({value[field] for value in receipt['claims'].values()}) != 3:
            raise ValueError('Each authorized claim must have a distinct pinned identity')
    for name, claim in receipt['claims'].items():
        uid = claim['claim_uid']
        import uuid
        if str(uuid.UUID(uid)) != uid or str(uuid.UUID(claim['pv_uid'])) != claim['pv_uid']:
            raise ValueError('Pinned Kubernetes object UIDs required')
        if claim['basename'] != 'pvc-' + uid + '_homelab-models_' + name:
            raise ValueError('Legacy volume path does not match claim identity')


def verify_stopped(receipt):
    deployments = api('/apis/apps/v1/namespaces/homelab-models/deployments')['items']
    by_name = {item['metadata']['name']: item for item in deployments}
    for name in ('ollama', 'odysseus', 'chromadb', 'searxng'):
        if by_name[name]['spec'].get('replicas', 1) != 0:
            raise ValueError('Legacy writer is not explicitly stopped')
    for pod in api('/api/v1/namespaces/homelab-models/pods')['items']:
        claims = {v.get('persistentVolumeClaim', {}).get('claimName') for v in pod['spec'].get('volumes', [])}
        if claims & set(CLAIMS) and not is_terminated(pod):
            raise ValueError('A legacy claim still has a Pod, including pending termination')
    for name, expected in receipt['claims'].items():
        claim = api('/api/v1/namespaces/homelab-models/persistentvolumeclaims/' + name)
        if claim['metadata']['uid'] != expected['claim_uid'] or claim['spec']['volumeName'] != expected['pv_name']:
            raise ValueError('Claim identity changed after receipt creation')
        pv = api('/api/v1/persistentvolumes/' + expected['pv_name'])
        if (pv['metadata']['uid'] != expected['pv_uid'] or
                pv['spec']['claimRef']['uid'] != expected['claim_uid'] or
                pv['spec'].get('hostPath', {}).get('path') != '/var/mnt/local-path-provisioner/' + expected['basename']):
            raise ValueError('Pinned legacy PV changed after receipt creation')


def erase_contents(fd, device):
    """Walk anchored descriptors; unlink symlinks themselves, never their targets."""
    if os.fstat(fd).st_dev != device:
        raise ValueError('Refusing to cross a filesystem')
    for name in os.listdir(fd):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                erase_contents(child, device)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=fd)
        else:
            os.unlink(name, dir_fd=fd)
    os.fsync(fd)


def main():
    record = api(RECORD)
    if record.get('immutable') is not True or record['metadata']['annotations'].get('homelab/reset-phase') != 'prepared':
        raise ValueError('Reset receipt is missing, mutable, already used or interrupted')
    receipt = json.loads(record['data']['receipt.json'])
    validate_receipt(receipt)
    verify_stopped(receipt)
    mount = open_mount('/var/mnt/local-path-provisioner', '/dev/sdb1')
    descriptors = []
    try:
        if filesystem_uuid(mount) != receipt['filesystem_uuid']:
            raise ValueError('Wrong worker filesystem')
        for target, project, limit in CLAIMS.values():
            fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=mount)
            try:
                attrs = project_attributes(fd)
                if (os.fstat(fd).st_dev != os.fstat(mount).st_dev or os.listdir(fd) or
                        attrs[3] != project or not attrs[0] & PROJINHERIT or get_quota(mount, project).hard * 512 != limit):
                    raise ValueError('Destination must be empty with the approved enforced quota')
            finally:
                os.close(fd)
        for value in receipt['claims'].values():
            fd = os.open(value['basename'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=mount)
            descriptors.append(fd)
            if os.fstat(fd).st_dev != os.fstat(mount).st_dev:
                raise ValueError('Legacy directory uses another filesystem')
        # A failed/ambiguous transition aborts before deletion. A started receipt
        # is never replayed automatically, even if the Pod died before a write.
        record = transition(record, 'started')
        verify_stopped(receipt)
        for fd in descriptors:
            erase_contents(fd, os.fstat(mount).st_dev)
        transition(record, 'completed')
        print('PASS: single-use reset completed for exactly three pinned legacy AI volumes', flush=True)
    finally:
        for fd in descriptors:
            os.close(fd)
        os.close(mount)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Reset stopped; inspect the durable receipt before any manual recovery', flush=True)
        raise SystemExit(1)
