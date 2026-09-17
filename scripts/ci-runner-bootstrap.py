#!/usr/bin/env python3
"""Record and apply the narrowly scoped initial CI hardware plan locally."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from ci_runner_plan import guard, guard_start
from worker_disk_plan import guard as guard_disk
from ci_retirement_plan import guard as guard_retirement, guard_ai_off
from local_lifecycle_tools import setup
from local_lifecycle_record import execution_lock, guard_environment, tree_digest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'live/proxmox/homelab'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private(path):
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Expected a private file owned by the operator')
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['plan', 'apply'])
    parser.add_argument('--stage', choices=['foundation', 'start', 'retirement', 'worker-disk'], default='foundation')
    parser.add_argument('--kubeconfig', type=Path)
    parser.add_argument('--maintenance-record', type=Path)
    parser.add_argument('--record-dir', type=Path, required=True)
    args = parser.parse_args()
    plan_guard = {'foundation': guard, 'start': guard_start, 'retirement': guard_retirement, 'worker-disk': guard_disk}[args.stage]
    os.umask(0o077)
    guard_environment()
    if any(k.startswith('AWS_ENDPOINT_URL') for k in os.environ):
        raise ValueError('AWS endpoint overrides are forbidden for live infrastructure')
    record_dir = args.record_dir.expanduser().resolve()
    record_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if record_dir.stat().st_uid != os.getuid() or record_dir.stat().st_mode & 0o077:
        raise ValueError('Record directory must be private')
    setup(record_dir)
    credentials = private(Path.home() / '.config/aws-account-infra/proxmox/credentials.json')
    if credentials['endpoint'] != 'https://pve.tail2f646b.ts.net/':
        raise ValueError('Unexpected Proxmox endpoint')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TF_', 'TOFU_', 'PROXMOX_VE_'))}
    env.update(AWS_PROFILE='admin', AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', PROXMOX_VE_ENDPOINT=credentials['endpoint'],
               PROXMOX_VE_API_TOKEN=credentials['api_token'])
    # Preserve certificate/hostname validation even when Mac MagicDNS is unavailable.
    from proxmox_peer_proxy import configure
    configure(env)
    command = ['tofu', '-chdir=' + str(DIRECTORY)]
    backend = json.loads((DIRECTORY / '.terraform/terraform.tfstate').read_text())['backend']
    expected = {'bucket': 'tofu-state-992382747916-us-east-1', 'key': 'proxmox/homelab/terraform.tfstate',
                'region': 'us-east-1', 'dynamodb_table': 'tofu-locks', 'encrypt': True}
    forbidden = ['endpoint', 'dynamodb_endpoint', 'iam_endpoint', 'sts_endpoint', 'endpoints',
                 'skip_credentials_validation', 'skip_requesting_account_id', 'skip_region_validation',
                 'skip_metadata_api_check', 'insecure', 'use_path_style', 'force_path_style']
    if any(backend['config'].get(k) for k in forbidden):
        raise ValueError('Nonstandard live backend endpoint or validation settings')
    if backend['type'] != 's3' or any(backend['config'].get(k) != v for k, v in expected.items()):
        raise ValueError('Unexpected state backend')
    if subprocess.check_output(command + ['workspace', 'show'], env=env).strip() != b'default':
        raise ValueError('Default workspace required')
    plan = record_dir / 'activation.tfplan'
    record_path = record_dir / 'record.json'
    with execution_lock():
        maintenance_sha = None
        if args.stage in ('retirement', 'worker-disk'):
            if (not args.kubeconfig or args.kubeconfig.is_symlink()
                    or args.kubeconfig.stat().st_mode & 0o077 or args.kubeconfig.stat().st_uid != os.getuid()):
                raise ValueError('Retirement requires a private owned kubeconfig to verify AI Off')
            kube = ['kubectl', '--kubeconfig', str(args.kubeconfig), '--request-timeout=30s']
            deployment = json.loads(subprocess.check_output(kube + ['get', 'deployment', 'ai-runtime',
                '-n', 'homelab-models', '-o', 'json'], timeout=35))
            pods = json.loads(subprocess.check_output(kube + ['get', 'pods', '-n', 'homelab-models',
                '-l', 'app=ai-runtime', '-o', 'json'], timeout=35))
            guard_ai_off(deployment, pods)
        if args.stage == 'worker-disk':
            from worker_disk_preflight import verify_host
            capacity = verify_host()
            (record_dir / ('preflight-' + args.operation + '.json')).write_text(json.dumps(capacity, indent=2))
        if args.stage == 'start':
            if not args.maintenance_record:
                raise ValueError('Worker recovery record is required before starting the manager')
            maintenance = private(args.maintenance_record)
            if maintenance.get('phase') != 'success' or maintenance.get('worker_memory_bytes') != 156 * 1024**3:
                raise ValueError('Worker maintenance has not verified the approved memory')
            maintenance_sha = digest(args.maintenance_record)
            live = json.loads(subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'root@10.0.0.92',
                'pvesh get /nodes/pve/qemu/102/status/current --output-format json'], timeout=30))
            if live['status'] != 'running' or int(live['maxmem']) != 156 * 1024**3:
                raise ValueError('Live worker memory/readiness prerequisite changed')
        if args.operation == 'plan':
            if record_path.exists() or plan.exists():
                raise ValueError('Use a new directory; previous execution evidence is retained')
            source_digest = tree_digest()
            variables = record_dir / 'activation.tfvars.json'
            variables.write_text(json.dumps({'vm_creation_approved': True}))
            with (record_dir / 'plan.log').open('wb') as log:
                subprocess.run(command + ['plan', '-input=false', '-lock-timeout=60s',
                    '-var-file=' + str(ROOT / 'config/environments/proxmox/homelab/vms.tfvars'),
                    '-var-file=' + str(variables), '-out=' + str(plan)], env=env, stdout=log,
                    stderr=subprocess.STDOUT, check=True)
            value = json.loads(subprocess.check_output(command + ['show', '-json', str(plan)], env=env))
            plan_guard(value)
            if tree_digest() != source_digest:
                raise ValueError('Source changed while planning')
            (record_dir / 'plan.json').write_text(json.dumps(value))
            record = {'execution': 'local', 'source_tree_sha256': source_digest,
                'plan_sha256': digest(plan), 'created_at': time.time(), 'apply': 'not-started',
                'backend': expected, 'changes': plan_guard(value), 'stage': args.stage, 'maintenance_sha256': maintenance_sha}
            record_path.write_text(json.dumps(record, indent=2) + '\n')
            print('PASS: exact initial CI plan recorded; no infrastructure applied')
            return
        record = private(record_path)
        if plan.is_symlink() or not plan.is_file() or plan.stat().st_uid != os.getuid() or plan.stat().st_mode & 0o077:
            raise ValueError('Saved plan must be a private owned regular file')
        if (record['execution'] != 'local' or record['source_tree_sha256'] != tree_digest()
                or record['plan_sha256'] != digest(plan) or record['backend'] != expected
                or record.get('stage') != args.stage or record.get('maintenance_sha256') != maintenance_sha
                or record['apply'] != 'not-started' or time.time() - record['created_at'] > 3600):
            raise ValueError('Saved plan stale, changed or already attempted; create a fresh record')
        value = json.loads(subprocess.check_output(command + ['show', '-json', str(plan)], env=env))
        plan_guard(value)
        # Worker restart is a separate maintenance step. The provider is explicitly
        # configured not to reboot automatically; this operation never powers off a VM.
        if args.stage == 'worker-disk':
            (record_dir / 'pre-apply-state.json').write_bytes(subprocess.check_output(command + ['state', 'pull'], env=env))
        record['apply'] = 'running'
        record_path.write_text(json.dumps(record, indent=2) + '\n')
        with (record_dir / 'apply.log').open('wb') as log:
            result = subprocess.run(command + ['apply', '-input=false', '-lock-timeout=60s', str(plan)],
                env=env, stdout=log, stderr=subprocess.STDOUT)
        record['apply'] = 'success' if result.returncode == 0 else 'failed'
        record['completed_at'] = time.time()
        record_path.write_text(json.dumps(record, indent=2) + '\n')
        print('Local hardware apply: ' + record['apply'] + '; worker restart and acceptance still required')
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
