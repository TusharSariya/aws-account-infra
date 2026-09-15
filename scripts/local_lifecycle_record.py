"""Explicit local execution records; independent of GitHub run identities."""
import hashlib
from contextlib import contextmanager
import fcntl
import stat
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def tree_digest():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split(b'\0')
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
        path = ROOT / os.fsdecode(name)
        digest.update(name + b'\0')
        digest.update(path.read_bytes() if path.exists() else b'<deleted>')
        digest.update(b'\0')
    return digest.hexdigest()


def read_record(path, applied=False):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077:
        raise ValueError('Local execution record must be private')
    value = json.loads(path.read_text())
    if value.get('execution') != 'local' or value.get('source_tree_sha256') != tree_digest():
        raise ValueError('Local execution source changed; create a new guarded plan')
    plan = path.parent / 'apps.tfplan'
    if plan.is_symlink() or not plan.is_file() or hashlib.sha256(plan.read_bytes()).hexdigest() != value.get('plan_sha256'):
        raise ValueError('Recorded saved plan changed')
    kubeconfig = path.parent / 'kubeconfig'
    if kubeconfig.is_symlink() or kubeconfig.stat().st_mode & 0o077 or hashlib.sha256(kubeconfig.read_bytes()).hexdigest() != value.get('kubeconfig_sha256'):
        raise ValueError('Recorded cluster credential identity changed')
    if applied and value.get('apply') != 'success':
        raise ValueError('Successful local guarded apply required before maintenance')
    return value


def guard_environment():
    if any(name.startswith('TF_CLI_ARGS') for name in os.environ) or os.environ.get('TF_DATA_DIR'):
        raise ValueError('Local execution rejects OpenTofu argument/data-directory overrides')
    if os.environ.get('TF_WORKSPACE', 'default') != 'default':
        raise ValueError('Local execution requires the default OpenTofu workspace')


def verify_backend(directory, run):
    backend = json.loads((directory / '.terraform/terraform.tfstate').read_text())['backend']
    expected = {'bucket': 'tofu-state-992382747916-us-east-1',
                'key': 'kubernetes/homelab/terraform.tfstate', 'region': 'us-east-1',
                'dynamodb_table': 'tofu-locks', 'encrypt': True}
    if backend['type'] != 's3' or any(backend['config'].get(k) != v for k, v in expected.items()):
        raise ValueError('Local OpenTofu backend differs from the recorded homelab backend')
    if run(['tofu', '-chdir=' + str(directory), 'workspace', 'show']).strip() != b'default':
        raise ValueError('Local execution requires the default OpenTofu workspace')


@contextmanager
def execution_lock():
    path = Path('/tmp') / ('homelab-lifecycle-' + str(os.getuid()) + '.lock')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Local execution lock must be a private owned regular file')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another local homelab lifecycle execution is running') from None
        yield
    finally:
        os.close(descriptor)
