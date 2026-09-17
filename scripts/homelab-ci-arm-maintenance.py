#!/usr/bin/env python3
"""Record and execute the exact worker-only binfmt extension maintenance."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
import yaml
from talos_tools import cli, private_dir
from local_lifecycle_record import execution_lock, tree_digest
from lifecycle_session import apps

ROOT = Path(__file__).resolve().parents[1]
storage_spec = importlib.util.spec_from_file_location('talos_storage_checks', ROOT/'scripts/talos-ci.py')
storage_checks = importlib.util.module_from_spec(storage_spec)
storage_spec.loader.exec_module(storage_checks)

OLD = 'factory.talos.dev/metal-installer/8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf:v1.13.9@sha256:d44d70c735408a1e51d2899da72276d7f5cf3b6f071becbcb72a1d0252ea190c'
NEW = 'factory.talos.dev/metal-installer/3b7472aeaf4f801ab6c24b777111445a0dcbb77b2be8e36e8d712cc2f9dc3dc9:v1.13.9@sha256:e5e30232d1069b02db72e5b0e9d502cad7dc13b7af2cb3e087a244550291be10'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def guard_storage_identity(receipt, vm_config, volumes, identities):
    if (vm_config['scsi1'] != receipt['data_disk']
            or volumes != receipt['persistent_volumes']
            or identities != receipt['partition_identities']):
        raise ValueError('Retained storage differs from the saved maintenance plan')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['plan', 'apply'])
    p.add_argument('--record', type=Path, required=True)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--talosconfig', type=Path, required=True)
    args = p.parse_args()
    directory = private_dir(args.record)
    for path in [args.kubeconfig, args.talosconfig]:
        if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
            raise ValueError('Private regular credentials required')
    kube = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    talos = [str(cli()), '--talosconfig', str(args.talosconfig), '--endpoints', '10.0.0.220', '--nodes', '10.0.0.222']
    def run(command, filename, timeout=120):
        path = directory / filename
        if path.exists():
            path = directory / (str(time.time_ns()) + '-' + filename)
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            path.write_bytes((error.stdout or b'') + b'\n' + (error.stderr or b''))
            path.chmod(0o600)
            raise ValueError('Command timed out; inspect private ' + path.name) from None
        path.write_bytes(result.stdout + b'\n' + result.stderr)
        path.chmod(0o600)
        if result.returncode:
            raise ValueError('Command failed; inspect private ' + filename)
        return result.stdout
    def get(*args):
        return json.loads(subprocess.check_output(kube + list(args) + ['-o', 'json']))
    def preflight():
        for name in ['talos-cp-01', 'talos-worker-01']:
            node = get('get', 'node', name)
            if not any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions']):
                raise ValueError('Both nodes must be Ready')
        if get('get','deployment','ai-runtime','-n','homelab-models')['spec']['replicas'] != 0 or get('get','pods','-n','homelab-models')['items']:
            raise ValueError('AI must be Off with termination observed')
        if get('get','pods','-n','arc-runners')['items'] or get('get','workloads','--all-namespaces')['items']:
            raise ValueError('All compute must finish before worker maintenance')
        if any(not c['spec'].get('suspend') for c in get('get','cronworkflows','-n','homelab-jobs')['items']):
            raise ValueError('Suspend ordinary schedules before maintenance')
        cfg = json.loads(run(['ssh','root@10.0.0.92','pvesh get /nodes/pve/qemu/102/config --output-format json'],'vm.json'))
        if cfg['name'] != 'talos-worker-01' or int(cfg['memory']) != 172*1024 or int(cfg['cores']) != 38 or 'size=1200G' not in cfg['scsi1'] or '02:42:00:00:01:02' not in cfg['net0']:
            raise ValueError('Worker VM identity/capacity mismatch')
        run(kube+['-n','homelab-services','rollout','status','deployment/pihole','--timeout=60s'],'dns-before.log')
        if int(cfg.get('onboot', 0)) != 1:
            raise ValueError('Worker automatic boot must remain enabled')
        cp_config = json.loads(run(['ssh','root@10.0.0.92','pvesh get /nodes/pve/qemu/100/config --output-format json'],'control-plane-vm.json'))
        effective = json.loads(run(['ssh','root@10.0.0.92','pvesh get /nodes/pve/qemu/102/status/current --output-format json'],'worker-status.json'))
        if int(cp_config.get('onboot',0)) != 1 or cp_config['name'] != 'talos-cp-01' or effective['status'] != 'running' or int(effective['maxmem']) != 172*1024**3:
            raise ValueError('Platform boot flags or effective worker RAM differ')
        volumes = sorted([{'uid':v['metadata']['uid'],'spec':v['spec']} for v in get('get','persistentvolumes')['items']],key=lambda v:v['uid'])
        if not volumes:
            raise ValueError('Retained persistent volumes must exist')
        resources = {}
        for kind in ['disks','discoveredvolumes','volumestatus','mountstatus']:
            resources[kind] = list(yaml.safe_load_all(run(talos+['get',kind,'-o','yaml'],kind+'.yaml')))
        if storage_checks.guard_storage_disks(resources['disks'],resources['discoveredvolumes']) != 'existing' or not storage_checks.check_storage_mount(resources['volumestatus'],resources['mountstatus']):
            raise ValueError('Retained storage is not mounted at the expected identity')
        mounts = [m['spec'] for m in resources['mountstatus'] if m['metadata']['id']==storage_checks.VOLUME]
        if len(mounts)!=1 or mounts[0].get('projectQuotaSupport') is not True:
            raise ValueError('Retained data mount must enforce XFS project quotas')
        identities = {v['spec']['dev_path']:[v['spec'].get('uuid'),v['spec'].get('partition_uuid')] for v in resources['discoveredvolumes'] if v['spec'].get('parent_dev_path')=='/dev/sdb'}
        if not identities or not all(all(value) for value in identities.values()):
            raise ValueError('Retained filesystem and partition UUIDs required')
        return get('get','node','talos-worker-01')['status']['nodeInfo']['bootID'], cfg, volumes, identities
    record = directory / 'receipt.json'
    with execution_lock():
        if args.operation == 'plan' and record.exists():
            raise ValueError('Use a new record directory')
        if args.operation == 'apply':
            saved = json.loads(record.read_text())
            if saved['status'] != 'planned' or time.time()-saved['created_at'] > 3600 or saved['source_sha256'] != tree_digest():
                raise ValueError('Attempt is not an unchanged fresh plan')
        boot, vm_config, volumes, identities = preflight()
        current = json.loads(run(talos+['get','machineconfig','v1alpha1','-o','json'],'machine-before.json'))['spec']
        docs = list(yaml.safe_load_all(current))
        machine = docs[0]['machine']
        if machine['type'] != 'worker' or machine['install']['disk'] != '/dev/sda' or machine['install'].get('wipe') or machine['install']['image'] != OLD:
            raise ValueError('Unexpected current worker install configuration')
        if machine.get('kernel', {}).get('modules'):
            raise ValueError('Existing kernel module configuration requires separate review')
        inventory = json.loads((ROOT/'config/environments/proxmox/homelab/talos/cluster.json').read_text())
        if next(n for n in inventory['nodes'] if n['name']=='talos-worker-01')['installer'] != NEW:
            raise ValueError('Reviewed installer pin differs')
        patch = {'machine': {'install': {'image': NEW}, 'kernel': {'modules': [{'name': 'binfmt_misc'}]}}}
        patch_path = directory/'patch.yaml'
        patch_path.write_text(yaml.safe_dump(patch)); patch_path.chmod(0o600)
        if args.operation == 'plan':
            if record.exists():
                raise ValueError('Use a new record directory')
            run(talos+['patch','machineconfig','--mode=staged','--dry-run','--patch','@'+str(patch_path)],'patch-preview.log')
            manifest = run(['docker','buildx','imagetools','inspect',NEW,'--raw'],'installer-index.json')
            if sha(manifest) != NEW.split('@sha256:')[1]:
                raise ValueError('Installer index digest mismatch')
            (directory/'original.machineconfig.yaml').write_text(current)
            (directory/'original.machineconfig.yaml').chmod(0o600)
            record.write_text(json.dumps({'source_sha256':tree_digest(),'created_at':time.time(),'current_sha256':sha(current.encode()),'boot_id':boot,'data_disk':vm_config['scsi1'],'persistent_volumes':volumes,'partition_identities':identities,'image':NEW,'status':'planned'},indent=2));record.chmod(0o600)
            print('PASS: worker-only module/installer patch preview and image digest; one graceful reboot planned')
            return
        receipt = json.loads(record.read_text())
        if receipt['status'] != 'planned' or time.time()-receipt['created_at'] > 3600 or receipt['source_sha256'] != tree_digest() or receipt['current_sha256'] != sha(current.encode()) or receipt['boot_id'] != boot:
            raise ValueError('Stale or modified maintenance plan')
        guard_storage_identity(receipt, vm_config, volumes, identities)
        try:
            receipt['status']='configuration-staging';record.write_text(json.dumps(receipt,indent=2))
            run(talos+['patch','machineconfig','--mode=staged','--patch','@'+str(patch_path)],'patch-apply.log')
            receipt['status']='upgrading';record.write_text(json.dumps(receipt,indent=2))
            run(talos+['upgrade','--image',NEW.replace(':v1.13.9@', '@'),'--reboot-mode','powercycle','--drain-timeout','5m','--timeout','15m','--wait'],'upgrade.log',timeout=930)
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                node=get('get','node','talos-worker-01')
                if node['status']['nodeInfo']['bootID']!=boot and any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions']):
                    break
                time.sleep(5)
            else:
                raise ValueError('Fresh Ready worker not observed')
            modules=run(talos+['read','/proc/modules'],'modules.log').decode()
            if 'binfmt_misc ' not in modules:
                raise ValueError('binfmt_misc not loaded')
            extensions=run(talos+['get','extensions'],'extensions.log').decode()
            if not all(name in extensions for name in ['binfmt-misc', 'gvisor', 'qemu-guest-agent']):
                raise ValueError('Expected worker extensions not observed')
            run(kube+['-n','homelab-services','rollout','status','deployment/pihole','--timeout=300s'],'dns-after.log',timeout=330)
            address=apps.tailnet_ip('pihole-dns.tail2f646b.ts.net')
            for mode in ['+tcp','+notcp']:
                answer=run(['dig','@'+address,'example.com','A','+short','+time=5','+tries=3',mode],'dns-'+mode[1:]+'.log').decode()
                if not answer.strip() or 'timed out' in answer:
                    raise ValueError('Pi-hole recovery failed')
            _, final_vm, final_volumes, final_identities = preflight()
            guard_storage_identity(receipt, final_vm, final_volumes, final_identities)
            for namespace, deployment in [('kueue-system','kueue-controller-manager'), ('arc-systems','arc-gha-rs-controller')]:
                run(kube+['-n',namespace,'rollout','status','deployment/'+deployment,'--timeout=300s'],deployment+'-ready.log',timeout=330)
            receipt['status']='success';receipt['completed_at']=time.time();record.write_text(json.dumps(receipt,indent=2))
            print('PASS: fresh worker boot, binfmt_misc loaded, Pi-hole recovered, no compute reservations')
        except Exception:
            receipt['status']='failed-or-verification-incomplete';record.write_text(json.dumps(receipt,indent=2))
            raise


if __name__ == '__main__':
    main()
