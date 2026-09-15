#!/usr/bin/env python3
"""Recover the exact image-delete permission failure without widening provider ACLs."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
from ci_retirement_plan import guard, guard_ai_off
from local_lifecycle_record import execution_lock, guard_environment, tree_digest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'scripts/ci-runner-bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--failed-record', type=Path, required=True)
    p.add_argument('--record-dir', type=Path, required=True)
    p.add_argument('--kubeconfig', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    guard_environment()
    if any(k.startswith(('AWS_ENDPOINT_URL', 'TF_VAR_', 'TOFU_CLI_ARGS')) for k in os.environ):
        raise ValueError('Infrastructure overrides forbidden')
    args.record_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    bootstrap.setup(args.record_dir)
    old = bootstrap.private(args.failed_record)
    original = args.failed_record.parent / 'activation.tfplan'
    if old.get('stage') != 'retirement' or old.get('apply') != 'failed' or bootstrap.digest(original) != old['plan_sha256']:
        raise ValueError('Expected unchanged failed retirement plan')
    command = ['tofu', '-chdir=' + str(bootstrap.DIRECTORY)]
    backend = json.loads((bootstrap.DIRECTORY / '.terraform/terraform.tfstate').read_text())['backend']
    if backend['type'] != 's3' or any(backend['config'].get(k) != v for k,v in old['backend'].items()):
        raise ValueError('Retirement backend changed')
    if any(v for k,v in backend['config'].items() if 'endpoint' in k or k.startswith('skip_')):
        raise ValueError('Backend overrides forbidden')
    if subprocess.check_output(command + ['workspace','show']).strip() != b'default':
        raise ValueError('Default workspace required')
    guard(json.loads(subprocess.check_output(command + ['show', '-json', str(original)])))
    log = (args.failed_record.parent / 'apply.log').read_text()
    if 'Datastore.Allocate' not in log or 'ci-ubuntu-24.04-20260911.qcow2' not in log:
        raise ValueError('Expected exact datastore permission failure')
    def host(script):
        return subprocess.check_output(['ssh', '-o', 'BatchMode=yes', 'server-10-42', script], timeout=120)
    kube = ['kubectl', '--kubeconfig', str(args.kubeconfig), '--request-timeout=30s']
    with execution_lock():
        guard_ai_off(json.loads(subprocess.check_output(kube + ['get','deployment','ai-runtime','-n','homelab-models','-o','json'])),
                     json.loads(subprocess.check_output(kube + ['get','pods','-n','homelab-models','-l','app=ai-runtime','-o','json'])))
        inventory = json.loads(host('pvesh get /nodes/pve/qemu --output-format json'))
        config = json.loads(host('pvesh get /nodes/pve/qemu/102/config --output-format json'))
        if any(int(v['vmid']) == 103 for v in inventory) or config['name'] != 'talos-worker-01' or int(config['memory']) != 172*1024:
            raise ValueError('Expected VM absence and already-restored worker configuration')
        receipt = dict(execution='local', stage='retirement', apply='running', source_tree_sha256=tree_digest(),
                       previous_record_sha256=bootstrap.digest(args.failed_record), recovery='exact-image-delete', started_at=time.time())
        record = args.record_dir / 'record.json'
        record.write_text(json.dumps(receipt, indent=2))
        # Immutable volume identity plus checksum, root SSH already used for maintenance.
        cleanup = '''set -eu
[ "$(hostname)" = pve ]
volume=local:import/ci-ubuntu-24.04-20260911.qcow2
path=$(pvesm path "$volume")
[ "$path" = /var/lib/vz/import/ci-ubuntu-24.04-20260911.qcow2 ]
[ ! -L "$path" ]
if [ -f "$path" ]; then
  printf '%s  %s\\n' 612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354 "$path" | sha256sum -c -
  pvesm free "$volume"
fi
[ ! -e "$path" ]
'''
        (args.record_dir / 'image-cleanup.log').write_bytes(host(cleanup))
        creds = bootstrap.private(Path.home()/'.config/aws-account-infra/proxmox/credentials.json')
        if creds['endpoint'] != 'https://pve.tail2f646b.ts.net/':
            raise ValueError('Unexpected endpoint')
        env = {k:v for k,v in os.environ.items() if not k.startswith(('TF_','TOFU_','PROXMOX_VE_'))}
        env.update(AWS_PROFILE='admin', AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', PROXMOX_VE_ENDPOINT=creds['endpoint'], PROXMOX_VE_API_TOKEN=creds['api_token'])
        plan = args.record_dir / 'post.tfplan'
        with (args.record_dir/'post-plan.log').open('wb') as output:
            result = subprocess.run(command + ['plan','-input=false','-detailed-exitcode','-lock-timeout=60s',
                '-var-file='+str(ROOT/'config/environments/proxmox/homelab/vms.tfvars'),'-var=vm_creation_approved=true','-out='+str(plan)], env=env, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise ValueError('Recovery requires a fresh empty hardware plan; inspect retained log')
        receipt.update(apply='success', completed_at=time.time(), post_plan_sha256=bootstrap.digest(plan))
        record.write_text(json.dumps(receipt, indent=2))
        print('PASS: exact image removed; fresh hardware plan empty; failed apply retained')


if __name__ == '__main__':
    main()
