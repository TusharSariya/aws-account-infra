#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Generate private inputs and run guarded Talos OpenTofu plans/applies.
No secret-bearing diagnostics, plan JSON or state are printed or uploaded.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
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
               'talos_machine_configuration_apply.worker[0]', 'helm_release.cilium'}
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
        if address == 'helm_release.cilium':
            if after.get('name') != 'cilium' or after.get('namespace') != 'kube-system':
                raise ValueError('Unexpected Cilium release target')
            if after.get('version') != '1.20.1' or after.get('chart') != './.terraform/cilium-1.20.1.tgz':
                raise ValueError('Cilium must use the pinned verified chart')
            values = yaml.safe_load(after.get('values', ['{}'])[0])
            if (values.get('kubeProxyReplacement') is not False
                    or values.get('routingMode') != 'tunnel'
                    or values.get('tunnelProtocol') != 'vxlan'
                    or values.get('ipam', {}).get('mode') != 'kubernetes'):
                raise ValueError('Cilium must retain kube-proxy, VXLAN and Kubernetes IPAM')
        summary.append({'resource': address, 'actions': actions,
                        'import': bool(item['change'].get('importing'))})
    if not any(s['resource'] == 'talos_machine_bootstrap.cluster' for s in summary):
        raise ValueError('Missing bootstrap adoption resource')
    return summary


def assert_public_state(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'client_key', 'client_certificate', 'machine_configuration',
                       'machine_configuration_input', 'client_configuration_wo',
                       'machine_configuration_input_wo'} and child not in (None, '', {}):
                raise ValueError('Sensitive Talos attribute persisted in state; inspect privately')
            assert_public_state(child)
    elif isinstance(value, list):
        for child in value:
            assert_public_state(child)


def download_verified(url, destination, expected):
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Downloaded artifact checksum mismatch')
    destination.write_bytes(data)


DATA_ID = '/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi1'
VOLUME = 'u-local-path-provisioner'
MOUNT = '/var/mnt/local-path-provisioner'
SELECTOR = ("!system_disk && disk.dev_path == '/dev/sdb' && disk.size == 1200u * GiB && "
            "'/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi1' in disk.symlinks")


def guard_storage_config(configs):
    expected = {'apiVersion': 'v1alpha1', 'kind': 'UserVolumeConfig',
                'name': 'local-path-provisioner', 'volumeType': 'partition',
                'provisioning': {'diskSelector': {'match': SELECTOR},
                                 'minSize': '1199GiB', 'grow': False},
                'filesystem': {'type': 'xfs'}}
    for name, config in configs.items():
        docs = list(yaml.safe_load_all(config))
        volumes = [d for d in docs if d.get('kind') == 'UserVolumeConfig']
        if volumes != ([expected] if name == 'talos-worker-01' else []):
            raise ValueError('User volume must target only the verified worker data disk')


def guard_storage_disks(disks, volumes):
    disks = {d['metadata']['id']: d['spec'] for d in disks}
    if disks.get('sda', {}).get('size') != 100 * 1024**3:
        raise ValueError('Worker OS disk identity/size mismatch')
    data = disks.get('sdb', {})
    if (data.get('size') != 1200 * 1024**3 or data.get('dev_path') != '/dev/sdb'
            or data.get('readonly') is not False or data.get('cdrom') is not False
            or DATA_ID not in data.get('symlinks', [])
            or sum(DATA_ID in d.get('symlinks', []) for d in disks.values()) != 1):
        raise ValueError('Worker data disk identity/size mismatch')
    specs = [v['spec'] for v in volumes]
    # Talos discovers an existing user volume by label. Reject misplaced duplicates too.
    labeled = [v for v in specs if v.get('partition_label') == VOLUME]
    data_volumes = [v for v in specs if v.get('dev_path') == '/dev/sdb'
                    or v.get('parent_dev_path') == '/dev/sdb']
    if len(data_volumes) == 1 and data_volumes[0].get('name') == '' and not labeled:
        return 'blank'
    partitions = [v for v in data_volumes if v.get('type') == 'partition']
    if (len(data_volumes) != 2 or len(partitions) != 1 or len(labeled) != 1
            or partitions[0] != labeled[0] or partitions[0].get('dev_path') != '/dev/sdb1'
            or partitions[0].get('name') != 'xfs'
            or partitions[0].get('size', 0) < 1199 * 1024**3):
        raise ValueError('Data disk contains unexpected existing content; refusing provisioning')
    return 'existing'


def check_storage_mount(volumes, mounts):
    volume = next((v['spec'] for v in volumes if v['metadata']['id'] == VOLUME), {})
    mount = next((m['spec'] for m in mounts if m['metadata']['id'] == VOLUME), {})
    return (volume.get('phase') == 'ready' and volume.get('location') == '/dev/sdb1'
            and mount.get('source') == '/dev/sdb1' and mount.get('target') == MOUNT
            and mount.get('filesystem') == 'xfs')


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
        secrets = base64.b64decode(os.environ.get('TALOS_SECRETS_B64', ''), validate=True).decode()
    identity = json.loads((INPUTS / 'identity.json').read_text())
    if hashlib.sha256(secrets.encode()).hexdigest() != identity['secrets_sha256']:
        raise ValueError('Existing cluster secrets fingerprint does not match')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='talos-ci-') as directory:
        private = Path(directory)
        (private / 'talos-secrets.yaml').write_text(secrets)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('TF_CLI_ARGS', 'TF_LOG', 'TOFU_LOG', 'TF_VAR_'))
               and k != 'TALOS_SECRETS_B64'}
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
        guard_storage_config(configs)
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
        kubeconfig = private / 'kubeconfig'
        run(tc + ['kubeconfig', kubeconfig, '--merge=false'])
        kube = yaml.safe_load(kubeconfig.read_text())
        if kube['clusters'][0]['cluster']['server'] != 'https://10.42.0.224:6443':
            raise ValueError('Unexpected Kubernetes API target')
        env['TF_VAR_kubeconfig_path'] = str(kubeconfig)
        env['KUBECONFIG'] = str(kubeconfig)
        # Authenticated dry-run exposes live config differences without applying them.
        # Keep its output private; it can contain secrets.
        dry_run = run(tc + ['apply-config', '--dry-run', '--mode=no-reboot',
                            '--file', output / 'talos-cp-01.machineconfig.yaml'])
        worker_tc = [cli, '--talosconfig', output / 'talosconfig', '-n', '10.42.0.222']
        def worker_resources(kind):
            return list(yaml.safe_load_all(run(worker_tc + ['get', kind, '-o', 'yaml'])))
        storage_before = guard_storage_disks(worker_resources('disks'), worker_resources('discoveredvolumes'))
        print('PASS: worker OS/data disk separation; data disk is ' + storage_before)
        run(worker_tc + ['apply-config', '--dry-run', '--mode=auto',
                         '--file', output / 'talos-worker-01.machineconfig.yaml'])
        tofu = ['tofu' , '-chdir=' + str(TF)]
        run(tofu + ['init', '-input=false', '-lockfile=readonly'])
        chart = TF / '.terraform/cilium-1.20.1.tgz'
        download_verified('https://helm.cilium.io/cilium-1.20.1.tgz', chart,
                          '06210eef7c23d15f7699c79e2fe3a1ec9c389024c5c5c006ea04022d322449a2')
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
            assert_public_state(json.loads(state))
            kube_user = kube['users'][0]['user']
            kube_credentials = [kube_user['client-key-data'], kube_user['client-certificate-data']]
            forbidden = [client['key'], client['crt'], secrets, *configs.values(),
                         *kube_credentials, *(base64.b64decode(v).decode() for v in kube_credentials)]
            if any(value and (value in state or json.dumps(value)[1:-1] in state) for value in forbidden):
                raise ValueError('Unexpected sensitive input persisted in state; inspect privately')
            for attempt in range(60):
                if check_storage_mount(worker_resources('volumestatus'), worker_resources('mountstatus')):
                    break
                time.sleep(5)
            else:
                raise ValueError('Worker data volume did not become mounted and ready')
            if guard_storage_disks(worker_resources('disks'), worker_resources('discoveredvolumes')) != 'existing':
                raise ValueError('Expected provisioned data volume')
            if storage_before == 'blank':
                def partition_identities():
                    return {v['spec']['dev_path']: (v['spec'].get('uuid'), v['spec'].get('partition_uuid'))
                            for v in worker_resources('discoveredvolumes')
                            if v['spec'].get('parent_dev_path') in ('/dev/sda', '/dev/sdb')}
                before_reboot = partition_identities()
                print('Verifying first-provisioned storage across a worker firmware reboot', flush=True)
                run(worker_tc + ['reboot', '--mode=powercycle', '--wait', '--timeout=8m'])
                if (before_reboot != partition_identities()
                        or not check_storage_mount(worker_resources('volumestatus'), worker_resources('mountstatus'))):
                    raise ValueError('Worker storage identities/mount changed across reboot')
                print('PASS: OS/data partition identities and data mount persist across worker reboot', flush=True)
            print('PASS: worker XFS data volume mounted at ' + MOUNT, flush=True)
            run(tc + ['etcd', 'members'])
            print('PASS: Talos CI apply and state secret-exclusion check', flush=True)
            kubectl = private / 'kubectl'
            download_verified('https://dl.k8s.io/release/v1.36.3/bin/linux/amd64/kubectl', kubectl,
                              'ebbd080e7c2e275093b55915722043257eb24004363e20acb3c4d71919f88336')
            kubectl.chmod(0o700)
            env['KUBECTL'] = str(kubectl)
            print(run(['bash', ROOT / 'scripts/homelab-cilium-validate.sh']))
        else:
            print('PASS: authenticated Talos preflight and guarded plan; no configuration applied')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(str(error) if isinstance(error, ValueError) else 'Talos CI failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
