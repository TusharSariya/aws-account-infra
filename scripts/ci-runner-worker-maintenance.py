#!/usr/bin/env python3
"""Gracefully restart only the Talos worker to apply the reviewed CI RAM budget."""
import argparse
from datetime import datetime
import json
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
    p.add_argument('--restore-for-kueue', action='store_true')
    p.add_argument('--record-dir', type=Path, required=True)
    p.add_argument('--bootstrap-record', type=Path, required=True)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--talosconfig', type=Path, required=True)
    args = p.parse_args()
    target_gib = 172 if args.restore_for_kueue else 156
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
        old_worker = get('get', 'node', 'talos-worker-01')
        old_boot = old_worker['status']['nodeInfo']['bootID']
        if args.restore_for_kueue:
            inventory = json.loads(host('pvesh get /nodes/pve/qemu --output-format json'))
            if any(int(vm['vmid']) == 103 for vm in inventory):
                raise ValueError('Retire VM 103 before restoring worker RAM')
            if bootstrap.get('stage') != 'retirement':
                raise ValueError('Successful guarded retirement receipt required')
        elif not args.restore_for_kueue and status(103)['status'] != 'stopped':
            raise ValueError('CI manager must remain stopped during worker resize')
        config = json.loads(host('pvesh get /nodes/pve/qemu/102/config --output-format json'))
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
        run(kube + ['-n', 'homelab-services', 'rollout', 'status', 'deployment/pihole', '--timeout=300s'])
        run(kube + ['-n', 'homelab-services', 'wait', 'service/pihole-dns',
                    '--for=condition=TailscaleProxyReady=true', '--timeout=300s'])
        for transport in ['+notcp', '+tcp']:
            answer = run(['dig', '@pihole-dns.tail2f646b.ts.net', 'example.com', 'A', '+short', '+time=5', '+tries=2', transport])
            if not answer.strip() or '0.0.0.0' in answer:
                raise ValueError('Pi-hole DNS recovery failed')
        if not args.restore_for_kueue and status(103)['status'] != 'stopped':
            raise ValueError('CI manager unexpectedly started during maintenance')
        evidence.update(boot_id=worker['status']['nodeInfo']['bootID'], phase='success', completed_at=time.time(), worker_memory_bytes=target_gib * 1024**3,
                        kubernetes_memory=memory, dns_transports=['udp', 'tcp'], manager='retired' if args.restore_for_kueue else 'stopped')
        receipt.write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'PASS: worker Ready at {target_gib} GiB and Pi-hole UDP/TCP recovered')


if __name__ == '__main__':
    main()
