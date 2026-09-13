#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Generate private inputs and run guarded Talos OpenTofu plans/applies.
No secret-bearing diagnostics, plan JSON or state are printed or uploaded.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/talos/homelab'
INPUTS = ROOT / 'config/environments/talos/homelab'


def load_generator():
    spec = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/homelab-talos-config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guard_plan(plan):
    allowed = {'talos_machine_configuration_apply.control_plane',
               'talos_machine_bootstrap.cluster',
               'talos_machine_configuration_apply.worker[0]'}
    summary = []
    for item in plan.get('resource_changes', []):
        address = item['address']
        actions = item['change']['actions']
        if address not in allowed or 'delete' in actions:
            raise ValueError('Unexpected resource or destructive action in Talos plan')
        if address == 'talos_machine_bootstrap.cluster' and actions not in (['no-op'], ['update']):
            raise ValueError('Existing bootstrap may only be imported or updated in state, never created again')
        after = item['change'].get('after') or {}
        if after.get('on_destroy', {}).get('reset', False):
            raise ValueError('Node reset must remain disabled')
        if address.endswith('.control_plane') and after.get('apply_mode') != 'no_reboot':
            raise ValueError('Control-plane apply must not reboot')
        summary.append({'resource': address, 'actions': actions,
                        'import': bool(item['change'].get('importing'))})
    if not any(s['resource'] == 'talos_machine_bootstrap.cluster' for s in summary):
        raise ValueError('Missing bootstrap adoption resource')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply'])
    parser.add_argument('--secrets-file', type=Path, help='Local preview only; CI uses environment secret')
    args = parser.parse_args()
    if args.action == 'apply' and os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Talos applies run through GitHub CI')
    if args.secrets_file:
        p = args.secrets_file.expanduser()
        if p.is_symlink() or p.stat().st_mode & 0o077 or p.stat().st_uid != os.getuid():
            raise ValueError('Cluster secrets must be privately owned with mode 0600')
        secrets = p.read_text()
    else:
        secrets = os.environ.get('TALOS_SECRETS_YAML', '')
    identity = json.loads((INPUTS / 'identity.json').read_text())
    if hashlib.sha256(secrets.encode()).hexdigest() != identity['secrets_sha256']:
        raise ValueError('Existing cluster secrets fingerprint does not match')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='talos-ci-') as directory:
        private = Path(directory)
        (private / 'talos-secrets.yaml').write_text(secrets)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('TF_CLI_ARGS', 'TF_LOG', 'TOFU_LOG', 'TF_VAR_'))
               and k != 'TALOS_SECRETS_YAML'}
        env.setdefault('AWS_PROFILE', 'admin') if not env.get('GITHUB_ACTIONS') else None
        def run(command):
            result = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=900)
            if result.returncode:
                # Commands can include multiline YAML errors or credentials in diagnostics.
                raise ValueError('Command failed: ' + Path(str(command[0])).name + '; private output suppressed')
            return result.stdout
        output = private / 'generated'
        run([sys.executable, ROOT / 'scripts/homelab-talos-config.py', 'generate',
             '--state-dir', private, '--output', output])
        configs = {name: (output / (name + '.machineconfig.yaml')).read_text()
                   for name in ['talos-cp-01', 'talos-worker-01']}
        for name, config in configs.items():
            docs = list(yaml.safe_load_all(config))
            if docs[0]['machine']['install']['disk'] != '/dev/sda':
                raise ValueError('Unexpected install disk')
        client = yaml.safe_load((output / 'talosconfig').read_text())['contexts']['homelab']
        env['TF_VAR_client_configuration'] = json.dumps({
            'ca_certificate': client['ca'], 'client_certificate': client['crt'], 'client_key': client['key']})
        env['TF_VAR_machine_configurations'] = json.dumps(configs)
        cli = load_generator().cli()
        tc = [cli, '--talosconfig', output / 'talosconfig', '-n', '10.42.0.220']
        status = yaml.safe_load(run(tc + ['get', 'machinestatus', '-o', 'yaml']))
        if status['spec']['stage'] != 'running':
            raise ValueError('Installed control plane must be running before adoption/update')
        run(tc + ['etcd', 'members'])
        # Authenticated dry-run exposes live config differences without applying them.
        # Keep its output private; it can contain secrets.
        dry_run = run(tc + ['apply-config', '--dry-run', '--mode=no-reboot',
                            '--file', output / 'talos-cp-01.machineconfig.yaml'])
        tofu = ['tofu', '-chdir=' + str(TF)]
        run(tofu + ['init', '-input=false', '-lockfile=readonly'])
        run(tofu + ['validate'])
        plan_file = private / 'tfplan'
        run(tofu + ['plan', '-input=false', '-lock-timeout=60s',
                    '-var-file=' + str(INPUTS / 'cluster.tfvars'), '-out=' + str(plan_file)])
        plan = json.loads(run(tofu + ['show', '-json', plan_file]))
        summary = guard_plan(plan)
        adopting = any(s['resource'].endswith('.control_plane') and 'create' in s['actions'] for s in summary)
        if adopting:
            if hashlib.sha256(configs['talos-cp-01'].encode()).hexdigest() != identity['initial_control_plane_sha256']:
                raise ValueError('Adoption must reuse the exact previously installed configuration')
            # A unified diff denotes live mismatch; refuse adoption rather than repair it implicitly.
            if '\n@@' in dry_run or '\n---' in dry_run or '\n+++' in dry_run:
                raise ValueError('Live configuration differs during adoption')
        print(json.dumps({'talos_plan': summary}, indent=2))
        if args.action == 'apply':
            run(tofu + ['apply', '-input=false', '-lock-timeout=60s', plan_file])
            # Write-only credentials/configuration must not appear in persisted state.
            state = run(tofu + ['state', 'pull'])
            forbidden = [client['key'], client['crt'], secrets, *configs.values()]
            if any(value and (value in state or json.dumps(value)[1:-1] in state) for value in forbidden):
                raise ValueError('Unexpected sensitive input persisted in state; inspect privately')
            run(tc + ['etcd', 'members'])
            print('PASS: Talos CI apply and state secret-exclusion check')
        else:
            print('PASS: authenticated Talos preflight and guarded plan; no configuration applied')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(str(error) if isinstance(error, ValueError) else 'Talos CI failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
