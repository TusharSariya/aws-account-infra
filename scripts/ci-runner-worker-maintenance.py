#!/usr/bin/env python3
"""Gracefully restart only the Talos worker to apply the reviewed CI RAM budget."""
import argparse
from datetime import datetime
import json
import hashlib
import yaml
import subprocess
import time
from pathlib import Path
from local_lifecycle_record import execution_lock, tree_digest
from talos_tools import cli, private_dir


def run(command):
    return subprocess.check_output(command, stderr=subprocess.STDOUT, timeout=360).decode()


def host(command):
    return run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'server-10-42', command])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--restore-for-kueue', action='store_true')
    modes.add_argument('--grow-os-disk', action='store_true')
    p.add_argument('--record-dir', type=Path, required=True)
    p.add_argument('--bootstrap-record', type=Path, required=True)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--talosconfig', type=Path, required=True)
    args = p.parse_args()
    target_gib = 172 if args.restore_for_kueue or args.grow_os_disk else 156
    directory = private_dir(args.record_dir)
    receipt = directory / 'worker-maintenance.json'
    if receipt.exists():
        raise ValueError('Maintenance already attempted; inspect previous evidence')
    kube = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    def get(*arguments):
        return json.loads(run(kube + list(arguments) + ['-o', 'json']))
    def status(identity):
        return json.loads(host('pvesh get /nodes/pve/qemu/' + str(identity) + '/status/current --output-format json'))
    with execution_lock():
        bootstrap = json.loads(args.bootstrap_record.read_text())
        if bootstrap.get('execution') != 'local' or bootstrap.get('apply') != 'success':
            raise ValueError('Successful recorded bootstrap apply required')
        if args.grow_os_disk:
            from worker_disk_plan import guard
            saved = args.bootstrap_record.parent / 'activation.tfplan'
            if hashlib.sha256(saved.read_bytes()).hexdigest() != bootstrap['plan_sha256']:
                raise ValueError('Saved disk plan changed')
            guard(json.loads((args.bootstrap_record.parent / 'plan.json').read_text()))
            workloads = get('get', 'workloads.kueue.x-k8s.io', '-A')['items']
            if any(not any(c['type']=='Finished' and c['status']=='True' for c in w.get('status', {}).get('conditions', [])) for w in workloads):
                raise ValueError('Quiesce compute before worker disk maintenance')
        old_worker = get('get', 'node', 'talos-worker-01')
        old_boot = old_worker['status']['nodeInfo']['bootID']
        if args.restore_for_kueue or args.grow_os_disk:
            inventory = json.loads(host('pvesh get /nodes/pve/qemu --output-format json'))
            if any(int(vm['vmid']) == 103 for vm in inventory):
                raise ValueError('Retire VM 103 before restoring worker RAM')
            if bootstrap.get('stage') != ('worker-disk' if args.grow_os_disk else 'retirement'):
                raise ValueError('Successful guarded retirement receipt required')
        elif not (args.restore_for_kueue or args.grow_os_disk) and status(103)['status'] != 'stopped':
            raise ValueError('CI manager must remain stopped during worker resize')
        config = json.loads(host('pvesh get /nodes/pve/qemu/102/config --output-format json'))
        if args.grow_os_disk and ('size=128G' not in config['scsi0'].split(',') or 'size=1200G' not in config['scsi1'].split(',')):
            raise ValueError('Expected expanded OS disk and unchanged data disk')
        if int(config['memory']) != target_gib * 1024 or int(config['cores']) != 38:
            raise ValueError('Expected pending worker memory configuration')
        if get('get', 'deployment', '-n', 'homelab-models', 'ai-runtime')['spec']['replicas'] != 0:
            raise ValueError('AI must be intentionally off before maintenance')
        cp = get('get', 'node', 'talos-cp-01')
        if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in cp['status']['conditions']):
            raise ValueError('Control plane is not Ready')
        evidence = {'source_tree_sha256': tree_digest(), 'started_at': time.time(), 'phase': 'shutdown-requested'}
        receipt.write_text(json.dumps(evidence, indent=2))
        talos = [str(cli()), '--talosconfig', str(args.talosconfig), '--endpoints', '10.42.0.220', '--nodes', '10.42.0.222']
        def volumes():
            return {d['metadata']['id']: d['spec'] for d in yaml.safe_load_all(run(talos + ['get', 'volumestatus', '-o', 'yaml'])) if d and d.get('spec', {}).get('filesystem') == 'xfs'}
        before_volumes = volumes() if args.grow_os_disk else {}
        if args.grow_os_disk:
            if before_volumes['EPHEMERAL']['parentLocation'] != '/dev/sda':
                raise ValueError('Unexpected EPHEMERAL disk')
            evidence['before_volumes'] = before_volumes
            receipt.write_text(json.dumps(evidence, indent=2))
        # No --force: Talos cordons/drains admitted workloads before shutting down.
        with (directory / 'worker-shutdown.log').open('w') as log:
            result = subprocess.run(talos + ['shutdown', '--timeout', '5m'], stdout=log, stderr=subprocess.STDOUT, timeout=330)
        if result.returncode != 0:
            raise ValueError('Graceful shutdown failed; inspect private log, never force automatically')
        deadline = time.monotonic() + 60
        while status(102)['status'] != 'stopped':
            if time.monotonic() >= deadline:
                raise ValueError('Worker shutdown not observed')
            time.sleep(2)
        started_at = time.time()
        host('qm start 102')
        deadline = time.monotonic() + 300
        while True:
            worker = get('get', 'node', 'talos-worker-01')
            lease = get('get', 'lease', '-n', 'kube-node-lease', 'talos-worker-01')
            renewed = datetime.fromisoformat(lease['spec']['renewTime'].replace('Z', '+00:00')).timestamp()
            fresh = worker['status']['nodeInfo']['bootID'] != old_boot and renewed > started_at
            if fresh and any(c['type'] == 'Ready' and c['status'] == 'True' for c in worker['status']['conditions']):
                memory = worker['status']['capacity']['memory']
                # Kernel/firmware reservations consume about 3.1 GiB on this guest.
                # Hypervisor effective RAM is checked exactly below.
                if memory.endswith('Ki') and (target_gib - 4) * 1024**2 < int(memory[:-2]) <= target_gib * 1024**2:
                    break
            if time.monotonic() >= deadline:
                raise ValueError('Worker readiness and effective memory not observed')
            time.sleep(5)
        final_worker = status(102)
        if final_worker['status'] != 'running' or int(final_worker['maxmem']) != target_gib * 1024**3:
            raise ValueError('Hypervisor effective worker memory differs')
        if args.grow_os_disk:
            after_volumes = volumes()
            for name, before in before_volumes.items():
                after = after_volumes[name]
                for key in ('uuid', 'partitionUUID', 'parentLocation', 'location'):
                    if before.get(key) != after.get(key):
                        raise ValueError('Filesystem identity changed: ' + name)
                if name != 'EPHEMERAL' and before['size'] != after['size']:
                    raise ValueError('Retained data volume changed size')
            if after_volumes['EPHEMERAL']['size'] - before_volumes['EPHEMERAL']['size'] != 28 * 1024**3:
                raise ValueError('Expected exactly 28 GiB EPHEMERAL growth')
            evidence['after_volumes'] = after_volumes
        run(kube + ['-n', 'homelab-services', 'rollout', 'status', 'deployment/pihole', '--timeout=300s'])
        run(kube + ['-n', 'homelab-services', 'wait', 'service/pihole-dns',
                    '--for=condition=TailscaleProxyReady=true', '--timeout=300s'])
        from lifecycle_session import apps
        dns_address = apps.tailnet_ip('pihole-dns.tail2f646b.ts.net')
        for transport in ['+notcp', '+tcp']:
            answer = run(['dig', '@' + dns_address, 'example.com', 'A', '+short', '+time=5', '+tries=2', transport])
            if not answer.strip() or '0.0.0.0' in answer:
                raise ValueError('Pi-hole DNS recovery failed')
        if not (args.restore_for_kueue or args.grow_os_disk) and status(103)['status'] != 'stopped':
            raise ValueError('CI manager unexpectedly started during maintenance')
        evidence.update(boot_id=worker['status']['nodeInfo']['bootID'], phase='success', completed_at=time.time(), worker_memory_bytes=target_gib * 1024**3,
                        kubernetes_memory=memory, dns_transports=['udp', 'tcp'], manager='retired' if args.restore_for_kueue or args.grow_os_disk else 'stopped')
        receipt.write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'PASS: worker Ready at {target_gib} GiB and Pi-hole UDP/TCP recovered')


if __name__ == '__main__':
    main()
