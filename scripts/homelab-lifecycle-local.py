#!/usr/bin/env python3
"""User-selected local saved-plan deployment and lifecycle maintenance, never CI impersonation."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

from local_lifecycle_record import ROOT, read_record, tree_digest, guard_environment, verify_backend, execution_lock
from lifecycle_session import apps
from local_lifecycle_tools import setup as setup_tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'apply', 'maintenance', 'idle'))
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--kubeconfig', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--confirm', choices=('run-local-lifecycle',), required=True)
    args = parser.parse_args()
    guard_environment()
    args.record = args.record.expanduser().resolve()
    if args.record == ROOT or ROOT in args.record.parents:
        raise apps.AppError("Private local records must be outside the repository")
    os.umask(0o077)
    if os.environ.get('GITHUB_ACTIONS'):
        raise apps.AppError('Local execution must not run as GitHub Actions')
    if args.credentials.stat().st_mode & 0o077 or args.kubeconfig.stat().st_mode & 0o077:
        raise apps.AppError('Private credential files required')
    os.environ['AI_LIFECYCLE_CREDENTIALS_B64'] = base64.b64encode(args.credentials.read_bytes()).decode()
    apps.lifecycle_credentials()
    receipt = args.record / 'receipt.json'
    if args.operation == 'plan':
        args.record.mkdir(mode=0o700, parents=False)
        shutil.copyfile(args.kubeconfig, args.record / 'kubeconfig')
        (args.record / 'kubeconfig').chmod(0o600)
    else:
        value = read_record(receipt, applied=args.operation != 'apply')
        if hashlib.sha256(args.kubeconfig.read_bytes()).hexdigest() != value['kubeconfig_sha256']:
            raise apps.AppError('Supplied kubeconfig differs from recorded cluster')
    os.environ['KUBECONFIG'] = str(args.record / 'kubeconfig')
    os.environ['TF_VAR_kubeconfig_path'] = str(args.record / 'kubeconfig')
    kubectl = setup_tools(args.record)
    os.environ['KUBECTL'] = kubectl
    os.environ['HOMELAB_LOCAL_RECEIPT'] = str(receipt)
    # GitHub API verifies existing image receipts; it does not run Actions.
    os.environ['GH_TOKEN'] = subprocess.check_output(['gh', 'auth', 'token'], stderr=subprocess.DEVNULL).decode().strip()
    nodes = json.loads(apps.run([kubectl, 'get', 'nodes', '-o', 'json']))['items']
    identities = {v['metadata']['name']: v['metadata']['uid'] for v in nodes}
    if set(identities) != {'talos-cp-01', 'talos-worker-01'} or any(
        not any(c['type'] == 'Ready' and c['status'] == 'True' for c in v['status']['conditions']) for v in nodes):
        raise apps.AppError('Existing Talos prerequisites are not Ready')
    if args.operation != 'plan' and identities != value['prerequisite_nodes']:
        raise apps.AppError('Recorded cluster node identities changed')
    command = ['tofu', '-chdir=' + str(apps.TF)]
    receipt = args.record / 'receipt.json'
    if args.operation == 'plan':
        apps.verify_ai_off(kubectl)
        apps.setup()
        apps.run(command + ['init', '-input=false', '-lockfile=readonly'])
        verify_backend(apps.TF, apps.run)
        apps.run(command + ['validate'])
        apps.schema_readiness(kubectl)
        apps.guard_images(remote=True)
        apps.execute('plan', args.record)
        value = {'execution': 'local', 'started_at': datetime.now(timezone.utc).isoformat(),
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
            'source_tree_sha256': tree_digest(), 'plan_sha256': (args.record / 'apps-plan.sha256').read_text(),
            'backend': 'kubernetes/homelab/terraform.tfstate', 'workspace': 'default',
            'kubeconfig_sha256': hashlib.sha256((args.record / 'kubeconfig').read_bytes()).hexdigest(), 'apply': 'pending',
            'prerequisite_nodes': {v['metadata']['name']: v['metadata']['uid'] for v in nodes}}
        receipt.write_text(json.dumps(value, indent=2) + '\n')
        print('PASS: local guarded plan recorded; no apply or AI Start performed')
        return
    value = read_record(receipt, applied=args.operation != 'apply')
    verify_backend(apps.TF, apps.run)
    if args.operation == 'apply':
        plan = args.record / 'apps.tfplan'
        if hashlib.sha256(plan.read_bytes()).hexdigest() != value['plan_sha256']:
            raise apps.AppError('Saved local plan changed')
        apps.guard_images(remote=True)
        apps.verify_ai_off(kubectl)
        data = apps.run(command + ['show', '-json', plan])
        apps.check_secrets(data, args.record)
        apps.guard_plan(json.loads(data))
        from postgres_preflight import verify as verify_postgres_capacity
        verify_postgres_capacity(kubectl, apps.run)
        apps.run(command + ['apply', '-input=false', '-lock-timeout=60s', plan])
        apps.check_secrets(apps.run(command + ['state', 'pull']), args.record)
        value['apply'] = 'success'
        value['applied_at'] = datetime.now(timezone.utc).isoformat()
        receipt.write_text(json.dumps(value, indent=2) + '\n')
        apps.verify_lifecycle(kubectl)
        print('PASS: local exact saved plan applied and intentional Off verified')
        return
    os.environ['AI_MAINTENANCE_CONFIRM'] = 'verify-ai-lifecycle-and-restore'
    os.environ['RUNNER_TEMP'] = str(args.record.resolve())
    os.environ['AI_BACKUP_OUTPUT'] = str((args.record / 'recovery').resolve())
    spec = importlib.util.spec_from_file_location('local_maintenance', ROOT / 'scripts/homelab-lifecycle-maintenance.py')
    maintenance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maintenance)
    # lifecycle_session was imported before KUBECTL was selected.
    import lifecycle_session
    lifecycle_session.KUBECTL = kubectl
    maintenance.KUBECTL = kubectl
    value[args.operation] = 'running'
    receipt.write_text(json.dumps(value, indent=2) + '\n')
    try:
        if args.operation == 'maintenance':
            maintenance.main()
        else:
            session = lifecycle_session.Maintenance()
            try:
                session.off()
                maintenance.recovery_idle(session)
            finally:
                session.command('stop')
                session.cleanup()
        value[args.operation] = 'success'
    except BaseException:
        value[args.operation] = 'failed'
        raise
    finally:
        value['finished_at'] = datetime.now(timezone.utc).isoformat()
        receipt.write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with execution_lock():
            main()
    except Exception as error:
        raise SystemExit(str(error) if isinstance(error, (apps.AppError, ValueError)) else
                         'Local lifecycle execution failed; private diagnostics suppressed') from None
