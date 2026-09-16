#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Focused private-input, plan/state and live-safety stages for the CI workflow.
No secret-bearing diagnostics, plan JSON or state are printed or uploaded.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/talos/homelab'
INPUTS = ROOT / 'config/environments/talos/homelab'
sys.path.insert(0, str(ROOT / 'scripts'))
from talos_tools import setup, cli, private_dir


class StageError(ValueError):
    """A deliberately secret-free diagnostic authored by this adapter."""



def guard_plan(plan):
    if plan.get('errored') or plan.get('complete') is False or plan.get('deferred_changes'):
        raise StageError('Complete successful Talos plan required')
    allowed = {'talos_machine_configuration_apply.control_plane',
               'talos_machine_bootstrap.cluster',
               'talos_machine_configuration_apply.worker[0]', 'helm_release.cilium',
               'helm_release.storage_policy', 'helm_release.local_path'}
    summary = []
    for item in plan.get('resource_changes', []):
        address = item['address']
        actions = item['change']['actions']
        if address not in allowed or 'delete' in actions:
            raise StageError('Unexpected resource or destructive action in Talos plan')
        if address == 'talos_machine_bootstrap.cluster' and actions not in (['no-op'], ['update']):
            raise StageError('Existing bootstrap may only be imported or updated in state, never created again')
        after = item['change'].get('after') or {}
        if after.get('on_destroy', {}).get('reset', False):
            raise StageError('Node reset must remain disabled')
        if address in {'talos_machine_configuration_apply.control_plane',
                       'talos_machine_configuration_apply.worker[0]'} and after.get('apply_mode') != 'no_reboot':
            raise StageError('Routine Talos apply must not reboot')
        if address == 'helm_release.cilium':
            if after.get('name') != 'cilium' or after.get('namespace') != 'kube-system':
                raise StageError('Unexpected Cilium release target')
            if after.get('version') != '1.20.1' or after.get('chart') != './.terraform/cilium-1.20.1.tgz':
                raise StageError('Cilium must use the pinned verified chart')
        if address == 'helm_release.local_path':
            if (after.get('name'), after.get('namespace'), after.get('version'), after.get('chart')) != (
                    'local-path-provisioner', 'local-path-storage', '0.0.37', './.terraform/local-path-provisioner'):
                raise StageError('Unexpected local-path release target/version')
            values = yaml.safe_load(after.get('values', ['{}'])[0])
            if (values.get('nodePathMap') != [
                    {'node': 'DEFAULT_PATH_FOR_NON_LISTED_NODES', 'paths': []},
                    {'node': 'talos-worker-01', 'paths': ['/var/mnt/local-path-provisioner']}]
                    or values.get('storageClass', {}).get('create') is not False):
                raise StageError('Storage must use only the worker data mount and explicit storage classes')
        if address == 'helm_release.storage_policy':
            if (after.get('name'), after.get('namespace'), after.get('version'), after.get('chart')) != (
                    'homelab-storage-policy', 'kube-system', '0.1.0', './charts/storage-policy'):
                raise StageError('Unexpected storage policy release target')
        summary.append({'resource': address, 'actions': actions,
                        'import': bool(item['change'].get('importing'))})
    if not any(s['resource'] == 'talos_machine_bootstrap.cluster' for s in summary):
        raise StageError('Missing bootstrap adoption resource')
    return summary


def assert_public_state(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'client_key', 'client_certificate', 'machine_configuration',
                       'machine_configuration_input', 'client_configuration_wo',
                       'machine_configuration_input_wo'} and child not in (None, '', {}):
                raise StageError('Sensitive Talos attribute persisted in state; inspect privately')
            assert_public_state(child)
    elif isinstance(value, list):
        for child in value:
            assert_public_state(child)


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
                'filesystem': {'type': 'xfs', 'projectQuotaSupport': True}}
    for name, config in configs.items():
        docs = list(yaml.safe_load_all(config))
        if name == 'talos-worker-01' and docs[0].get('machine', {}).get('sysctls', {}).get('user.max_user_namespaces') != '11255':
            raise StageError('Worker user namespaces are required to prevent project quota bypass')
        volumes = [d for d in docs if d.get('kind') == 'UserVolumeConfig']
        if volumes != ([expected] if name == 'talos-worker-01' else []):
            raise StageError('User volume must target only the verified worker data disk')


def guard_storage_disks(disks, volumes):
    disks = {d['metadata']['id']: d['spec'] for d in disks}
    if disks.get('sda', {}).get('size') != 192 * 1024**3:
        raise StageError('Worker OS disk identity/size mismatch')
    data = disks.get('sdb', {})
    if (data.get('size') != 1200 * 1024**3 or data.get('dev_path') != '/dev/sdb'
            or data.get('readonly') is not False or data.get('cdrom') is not False
            or DATA_ID not in data.get('symlinks', [])
            or sum(DATA_ID in d.get('symlinks', []) for d in disks.values()) != 1):
        raise StageError('Worker data disk identity/size mismatch')
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
        raise StageError('Data disk contains unexpected existing content; refusing provisioning')
    return 'existing'


def check_storage_mount(volumes, mounts):
    volume = next((v['spec'] for v in volumes if v['metadata']['id'] == VOLUME), {})
    mount = next((m['spec'] for m in mounts if m['metadata']['id'] == VOLUME), {})
    return (volume.get('phase') == 'ready' and volume.get('location') == '/dev/sdb1'
            and mount.get('source') == '/dev/sdb1' and mount.get('target') == MOUNT
            and mount.get('filesystem') == 'xfs')


def clean_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('TF_CLI_ARGS', 'TF_LOG', 'TOFU_LOG', 'TF_VAR_'))
           and k not in {'TALOS_SECRETS_B64', 'TF_DATA_DIR', 'TF_WORKSPACE'}}
    if not env.get('GITHUB_ACTIONS'):
        env.setdefault('AWS_PROFILE', 'admin')
    return env


def run_private(command, env):
    result = subprocess.run(list(map(str, command)), env=env,
                            capture_output=True, text=True, timeout=900)
    if result.returncode:
        # Only fixed check identifiers and line numbers cross the private boundary.
        # Never forward command output, exception text, resource YAML or credentials.
        import re
        for line in result.stderr.splitlines():
            if re.fullmatch(r'ACCEPTANCE_DIAGNOSTIC: (?:(?:network|readiness|storage|capacity|lifecycle) line [0-9]{1,4}|probe (?:api-read|namespace-dry-run) (?:success|failure|timeout)|error (?:Forbidden|InternalError|Unauthorized|failed-calling-webhook|connection-refused|timeout|no-endpoints-available|AlreadyExists|ServiceUnavailable|certificate|EOF))', line):
                print(line, file=sys.stderr)
        raise StageError('Private command failed: ' + Path(str(command[0])).name
                         + '; exit ' + str(result.returncode) + '; output suppressed')
    return result.stdout


def prepare(private, source):
    if any(private.iterdir()):
        raise StageError('Private workspace must be empty')
    if source:
        source = source.expanduser()
        if source.is_symlink() or source.stat().st_mode & 0o077 or source.stat().st_uid != os.getuid():
            raise StageError('Cluster secrets must be privately owned with mode 0600')
        secrets = source.read_text()
    else:
        secrets = base64.b64decode(os.environ.get('TALOS_SECRETS_B64', ''), validate=True).decode()
    identity = json.loads((INPUTS / 'identity.json').read_text())
    if hashlib.sha256(secrets.encode()).hexdigest() != identity['secrets_sha256']:
        raise StageError('Existing cluster secrets fingerprint does not match')
    (private / 'talos-secrets.yaml').write_text(secrets)
    run_private([sys.executable, ROOT / 'scripts/homelab-talos-config.py', 'generate',
                 '--state-dir', private, '--output', private / 'generated'], clean_environment())


class Session:
    """Private identity boundary shared by independently invoked CI stages."""
    def __init__(self, private):
        self.private = private
        self.output = private / 'generated'
        self.secrets = (private / 'talos-secrets.yaml').read_text()
        self.identity = json.loads((INPUTS / 'identity.json').read_text())
        if hashlib.sha256(self.secrets.encode()).hexdigest() != self.identity['secrets_sha256']:
            raise StageError('Existing cluster secrets fingerprint does not match')
        self.configs = {name: (self.output / (name + '.machineconfig.yaml')).read_text()
                        for name in ['talos-cp-01', 'talos-worker-01']}
        for config in self.configs.values():
            if next(yaml.safe_load_all(config))['machine']['install']['disk'] != '/dev/sda':
                raise StageError('Unexpected install disk')
        guard_storage_config(self.configs)
        self.client = yaml.safe_load((self.output / 'talosconfig').read_text())['contexts']['homelab']
        self.env = clean_environment()
        self.env['TF_VAR_client_configuration'] = json.dumps({
            'ca_certificate': self.client['ca'], 'client_certificate': self.client['crt'],
            'client_key': self.client['key']})
        self.env['TF_VAR_machine_configurations'] = json.dumps(self.configs)
        self.env['TF_VAR_kubeconfig_path'] = str(private / 'kubeconfig')
        self.env['KUBECONFIG'] = str(private / 'kubeconfig')
        binary = cli()
        self.env['TALOSCTL'] = str(binary)
        self.env['TALOSCONFIG'] = str(self.output / 'talosconfig')
        self.env['KUBECTL'] = str(binary.parent / 'kubectl-v1.36.3')
        self.tc = [binary, '--talosconfig', self.output / 'talosconfig', '-n', '10.42.0.220']
        self.worker_tc = [binary, '--talosconfig', self.output / 'talosconfig', '-n', '10.42.0.222']

    def run(self, command):
        return run_private(command, self.env)

    def worker_resources(self, kind):
        return list(yaml.safe_load_all(self.run(self.worker_tc + ['get', kind, '-o', 'yaml'])))

    def connect(self):
        status = yaml.safe_load(self.run(self.tc + ['get', 'machinestatus', '-o', 'yaml']))
        if status['spec']['stage'] != 'running':
            raise StageError('Installed control plane must be running before adoption/update')
        self.run(self.tc + ['etcd', 'members'])
        self.run(self.tc + ['kubeconfig', self.private / 'kubeconfig', '--merge=false'])
        kube = yaml.safe_load((self.private / 'kubeconfig').read_text())
        if kube['clusters'][0]['cluster']['server'] != 'https://10.42.0.224:6443':
            raise StageError('Unexpected Kubernetes API target')
    def preflight(self):
        self.connect()
        dry_run = self.run(self.tc + ['apply-config', '--dry-run', '--mode=no-reboot',
                           '--file', self.output / 'talos-cp-01.machineconfig.yaml'])
        (self.private / 'dry-run.txt').write_text(dry_run)
        storage = guard_storage_disks(self.worker_resources('disks'), self.worker_resources('discoveredvolumes'))
        (self.private / 'storage-before.txt').write_text(storage)
        self.run(self.worker_tc + ['apply-config', '--dry-run', '--mode=no-reboot',
                                  '--file', self.output / 'talos-worker-01.machineconfig.yaml'])
        print('PASS: authenticated Talos preflight; worker data disk is ' + storage)

    def guard(self):
        plan_file = self.private / 'tfplan'
        plan = json.loads(self.run(['tofu', '-chdir=' + str(TF), 'show', '-json', plan_file]))
        summary = guard_plan(plan)
        if any(s['resource'].endswith('.control_plane') and 'create' in s['actions'] for s in summary):
            if hashlib.sha256(self.configs['talos-cp-01'].encode()).hexdigest() != self.identity['initial_control_plane_sha256']:
                raise StageError('Adoption must reuse the exact previously installed configuration')
            dry_run = (self.private / 'dry-run.txt').read_text()
            if any(marker in dry_run for marker in ('\n@@', '\n---', '\n+++')):
                raise StageError('Live configuration differs during adoption')
        # The independently invoked apply stage only consumes this exact guarded plan.
        (self.private / 'guarded-plan.sha256').write_text(hashlib.sha256(plan_file.read_bytes()).hexdigest())
        print(json.dumps({'talos_plan': summary}, indent=2))

    def execute(self, command):
        # Native OpenTofu command remains visible in YAML, secret inputs stay here.
        if command[:2] != ['tofu', '-chdir=live/talos/homelab'] or len(command) < 3:
            raise StageError('Expected an explicit Talos OpenTofu command')
        operation = command[2]
        if operation not in ('init', 'validate', 'plan', 'apply'):
            raise StageError('Unsupported OpenTofu operation')
        if operation == 'apply':
            if os.environ.get('GITHUB_ACTIONS') != 'true':
                raise StageError('Talos applies run through GitHub CI')
            expected = ['tofu', '-chdir=live/talos/homelab', 'apply', '-input=false',
                        '-lock-timeout=60s', str(self.private / 'tfplan')]
            if command != expected:
                raise StageError('Apply must consume the guarded saved plan')
            digest = hashlib.sha256((self.private / 'tfplan').read_bytes()).hexdigest()
            if digest != (self.private / 'guarded-plan.sha256').read_text():
                raise StageError('Saved plan changed after review')
        self.run(command)
        print('PASS: OpenTofu ' + operation + ' (private diagnostics suppressed)')

    def state(self):
        state = self.run(['tofu', '-chdir=' + str(TF), 'state', 'pull'])
        assert_public_state(json.loads(state))
        kube_user = yaml.safe_load((self.private / 'kubeconfig').read_text())['users'][0]['user']
        credentials = [kube_user['client-key-data'], kube_user['client-certificate-data']]
        forbidden = [self.client['key'], self.client['crt'], self.secrets, *self.configs.values(),
                     *credentials, *(base64.b64decode(v).decode() for v in credentials)]
        if any(value and (value in state or json.dumps(value)[1:-1] in state) for value in forbidden):
            raise StageError('Unexpected sensitive input persisted in state; inspect privately')
        print('PASS: state secret-exclusion check')

    def storage(self):
        # Routine readiness never reboots. First provisioning requests a separate gate.
        for attempt in range(60):
            if check_storage_mount(self.worker_resources('volumestatus'), self.worker_resources('mountstatus')):
                break
            time.sleep(5)
        else:
            raise StageError('Worker data volume did not become mounted and ready')
        if guard_storage_disks(self.worker_resources('disks'), self.worker_resources('discoveredvolumes')) != 'existing':
            raise StageError('Expected provisioned data volume')
        before = self.private / 'storage-before.txt'
        first = before.exists() and before.read_text() == 'blank'
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('needs_worker_reboot=' + str(first).lower() + '\n')
        self.run(self.tc + ['etcd', 'members'])
        print('PASS: worker data mount and etcd readiness')


    def readiness(self):
        self.storage()
        print(self.run(['bash', ROOT / 'scripts/homelab-readiness.sh']))

    def worker_reboot(self):
        if os.environ.get('HOMELAB_WORKER_REBOOT_APPROVED') != 'true':
            raise StageError('Worker reboot requires explicit maintenance approval')
        self.storage()
        def identities():
            return {v['spec']['dev_path']: (v['spec'].get('uuid'), v['spec'].get('partition_uuid'))
                    for v in self.worker_resources('discoveredvolumes')
                    if v['spec'].get('parent_dev_path') in ('/dev/sda', '/dev/sdb')}
        before = identities()
        if not before or not any(path.startswith('/dev/sdb') for path in before):
            raise StageError('Expected provisioned worker partition identities')
        self.run(self.worker_tc + ['reboot', '--mode=powercycle', '--wait', '--timeout=8m'])
        self.readiness()
        if before != identities():
            raise StageError('Worker partition identities changed across reboot')
        mounts = [item.get('spec', {}) for item in self.worker_resources('mountstatus')
                  if item.get('metadata', {}).get('id') == VOLUME]
        if (len(mounts) != 1 or mounts[0].get('source') != '/dev/sdb1'
                or mounts[0].get('target') != MOUNT or mounts[0].get('filesystem') != 'xfs'
                or mounts[0].get('projectQuotaSupport') is not True):
            raise StageError('Worker data mount must activate project quotas after maintenance')
        print('PASS: explicit worker reboot preserves partition identities and activates XFS project quotas; write enforcement remains a separate check')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['setup', 'prepare', 'preflight', 'exec', 'guard',
                                         'state', 'storage', 'readiness', 'connect', 'worker-reboot', 'network', 'pvc', 'capacity', 'lifecycle', 'lifecycle-maintenance', 'capacity-credentials', 'ai-migrate', 'quota-prepare', 'quota-verify'])
    parser.add_argument('--private', type=Path)
    parser.add_argument('--secrets-file', type=Path)
    parser.add_argument('--acceptance', action='store_true')
    parser.add_argument('--checks-only', action='store_true')
    args, command = parser.parse_known_args()
    os.umask(0o077)
    if args.stage == 'setup':
        setup(args.acceptance, charts=not args.checks_only)
        print('PASS: checksum-verified deployment tools and charts')
        return
    if not args.private:
        raise StageError('A private workspace is required')
    private = private_dir(args.private)
    if args.stage == 'prepare':
        prepare(private, args.secrets_file)
        return
    session = Session(private)
    if args.stage == 'exec':
        session.execute(command[1:] if command[:1] == ['--'] else command)
    elif args.stage == 'network':
        print(session.run(['bash', ROOT / 'scripts/homelab-cilium-validate.sh']))
    elif args.stage in ('quota-prepare', 'quota-verify'):
        print(session.run([sys.executable, ROOT / 'scripts/quota-acceptance.py', args.stage.removeprefix('quota-')]))
    elif args.stage == 'ai-migrate':
        print(session.run([sys.executable, ROOT / 'scripts/ai-migration.py']))
    elif args.stage == 'capacity-credentials':
        print(session.run([sys.executable, ROOT / 'scripts/homelab-capacity-credentials.py']))
    elif args.stage == 'lifecycle-maintenance':
        # Only this explicitly selected reviewed maintenance recipe gets the longer
        # deadline. Its output consists of fixed proof labels, never private objects.
        result = subprocess.run([sys.executable, ROOT / 'scripts/homelab-lifecycle-maintenance.py'],
                                env=session.env, timeout=5100)
        if result.returncode:
            raise StageError('Lifecycle maintenance failed')
    elif args.stage == 'lifecycle':
        print(session.run([sys.executable, ROOT / 'scripts/homelab-lifecycle-validate.py']))
    elif args.stage == 'capacity':
        print(session.run([sys.executable, ROOT / 'scripts/homelab-capacity-validate.py']))
    elif args.stage == 'pvc':
        print(session.run([sys.executable, ROOT / 'scripts/homelab-storage-validate.py']))
    else:
        getattr(session, args.stage.replace('-', '_'))()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # YAML/JSON/parser exceptions and external tool output can contain credentials.
        print(str(error) if isinstance(error, StageError) else
              'Talos stage failed (' + type(error).__name__ + '); private diagnostics suppressed', file=sys.stderr)
        sys.exit(1)
