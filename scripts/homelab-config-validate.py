#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Cross-check public Proxmox inputs against private generated Talos configs.
Run with uv run scripts/homelab-config-validate.py --generated-dir PRIVATE_DIR.
Requires initialized OpenTofu root. Does not contact any live node.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/environments/proxmox/homelab/talos'
CP, WORKER = 'talos-cp-01', 'talos-worker-01'
SCHEMATICS = {
    CP: 'ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515',
    WORKER: '3b7472aeaf4f801ab6c24b777111445a0dcbb77b2be8e36e8d712cc2f9dc3dc9',
}


def require(condition, description):
    if not condition:
        raise ValueError(description)


def check(vms, inventory, documents):
    require(set(vms) == {CP, WORKER}, 'Expected exactly two VM identities')
    require({n['name'] for n in inventory['nodes']} == set(vms) and len(inventory['nodes']) == 2,
            'Talos and Proxmox node sets differ')
    require(inventory['kubernetes_version'] == 'v1.36.3', 'Kubernetes pin drift')
    require(inventory['endpoint'] == 'https://10.0.0.231:6443' and inventory['talos_endpoint'] == '10.0.0.220', 'Endpoint drift')
    for node in inventory['nodes']:
        name = node['name']
        cp = name == CP
        vm = vms[name]
        require((vm['vcpus'], vm['memory_gib'], vm['disks_gib']) ==
                ((2, 4, [100]) if cp else (38, 172, [320, 1200])), name + ': capacity drift')
        require((vm['vm_id'], vm['ipv4_address'], vm['mac_address'], vm['startup_order']) ==
                ((100, '10.0.0.220', '02:42:00:00:01:00', 1) if cp else
                 (102, '10.0.0.222', '02:42:00:00:01:02', 2)), name + ': identity drift')
        suffix = 'qemu' if cp else 'qemu-gvisor'
        require(vm['iso_file_id'] == f'local:iso/talos-v1.13.9-{suffix}-amd64.iso' and vm['guest_agent'], name + ': ISO/agent drift')
        docs = documents[name]
        cfg = docs[0]
        machine, cluster = cfg['machine'], cfg['cluster']
        require(machine['type'] == ('controlplane' if cp else 'worker'), name + ': role drift')
        require(machine['install']['disk'] == '/dev/sda' and not machine['install'].get('wipe', False), name + ': unsafe install disk/wipe')
        expected = f"factory.talos.dev/metal-installer/{SCHEMATICS[name]}:v1.13.9@sha256:"
        image = machine['install']['image']
        require(image == node['installer'] and image.startswith(expected) and len(image.removeprefix(expected)) == 64, name + ': schematic/version/digest drift')
        if not cp:
            require(machine.get('kernel', {}).get('modules') == [{'name': 'binfmt_misc'}], name + ': ARM kernel module drift')
        require(machine['kubelet']['image'].endswith(':v1.36.3'), name + ': kubelet version drift')
        require(cluster['network']['cni']['name'] == 'none' and not cluster['proxy'].get('disabled', False), name + ': bootstrap CNI/proxy drift')
        require(cluster['controlPlane']['endpoint'] == inventory['endpoint'], name + ': API endpoint drift')
        require(not cluster.get('allowSchedulingOnControlPlanes', False), name + ': control-plane scheduling enabled')
        label = 'trusted' if cp else 'shared'
        require(machine['nodeLabels'].get('workload.security/' + label) == 'true', name + ': role label missing')
        require('workload.security/sandbox' not in machine['nodeLabels'] and
                'workload.security/sandbox' not in machine.get('nodeTaints', {}) and
                'workload.security/sandbox' not in machine['kubelet'].get('extraArgs', {}).get('register-with-taints', ''), name + ': obsolete sandbox isolation marker')
        kinds = {d.get('kind'): d for d in docs[1:]}
        require(kinds['HostnameConfig']['hostname'] == name, name + ': hostname drift')
        require(kinds['LinkAliasConfig']['selector']['match'] == f'mac(link.permanent_addr) == "{vm["mac_address"]}"', name + ': NIC MAC drift')
        require(kinds['DHCPv4Config']['name'] == kinds['LinkAliasConfig']['name'] == 'homelab', name + ': DHCP link drift')
        require(kinds['DHCPv4Config']['clientIdentifier'] == 'mac', name + ': DHCP identity drift')
        require(('Layer2VIPConfig' in kinds) == cp, name + ': VIP placement drift')
        if cp:
            require(kinds['Layer2VIPConfig']['name'] == '10.0.0.231' and kinds['Layer2VIPConfig']['link'] == 'homelab', 'VIP identity drift')
        require(not machine.get('network', {}).get('kubespan', {}).get('enabled', False) and 'KubeSpanConfig' not in kinds, 'KubeSpan unexpectedly enabled')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated-dir', required=True, type=Path)
    parser.add_argument('--self-test', action='store_true', help='Also prove representative drift is rejected in memory')
    args = parser.parse_args()
    generated = args.generated_dir.expanduser().resolve()
    require(ROOT not in generated.parents and generated != ROOT, 'Generated configs must be outside the checkout')
    require(generated.stat().st_mode & 0o077 == 0, 'Generated directory permissions are too broad')
    result = subprocess.run(['tofu', '-chdir=' + str(ROOT / 'live/proxmox/homelab'), 'console',
                             '-var-file=' + str(CONFIG.parent / 'vms.tfvars')],
                            input='jsonencode(var.vms)\n', text=True, capture_output=True, check=True)
    vms = json.loads(json.loads(result.stdout))
    inventory = json.loads((CONFIG / 'cluster.json').read_text())
    documents = {}
    module_spec = importlib.util.spec_from_file_location('talos_generator', ROOT / 'scripts/homelab-talos-config.py')
    generator = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(generator)
    binary = generator.cli()
    with tempfile.TemporaryDirectory(prefix='talos-validation-') as diagnostic_dir:
        for node in inventory['nodes']:
            name = node['name']
            path = generated / (name + '.machineconfig.yaml')
            require(not path.is_symlink() and path.stat().st_mode & 0o077 == 0, 'Machine config permissions are too broad')
            generator.run(binary, ['validate', '--config', path, '--mode', 'metal', '--strict'], Path(diagnostic_dir) / 'validation.log')
            documents[name] = list(yaml.safe_load_all(path.read_text()))
    check(vms, inventory, documents)
    client_path = generated / 'talosconfig'
    require(not client_path.is_symlink() and client_path.stat().st_mode & 0o077 == 0, 'Talos client config permissions are too broad')
    context = yaml.safe_load(client_path.read_text())['contexts'][inventory['name']]
    require(context['endpoints'] == ['10.0.0.220'] and context['nodes'] == ['10.0.0.220'], 'Talos client must use the actual control plane')
    for filename in ['talos-secrets.yaml', 'talosconfig', CP + '.machineconfig.yaml', WORKER + '.machineconfig.yaml']:
        require(subprocess.run(['git', 'check-ignore', '--quiet', '--no-index', filename], cwd=ROOT).returncode == 0, 'Missing secret exclusion')
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    require(not any(Path(p).name in {'talos-secrets.yaml', 'talosconfig'} or p.endswith('.machineconfig.yaml') for p in tracked), 'Secret artifact is tracked')
    if args.self_test:
        # Mutate only in memory. Never print or persist secret-bearing fixtures.
        for field, value in [('image', documents[CP][0]['machine']['install']['image']), ('disk', '/dev/sdb')]:
            changed = copy.deepcopy(documents)
            changed[WORKER][0]['machine']['install'][field] = value
            try:
                check(vms, inventory, changed)
            except ValueError:
                continue
            raise ValueError('Validation self-test failed to reject installer/disk drift')
        changed_vms = copy.deepcopy(vms)
        changed_vms[WORKER]['memory_gib'] = 180
        try:
            check(changed_vms, inventory, documents)
        except ValueError:
            pass
        else:
            raise ValueError('Validation self-test failed to reject memory drift')
        print('PASS: wrong schematic, data-disk install target and memory drift rejected')
    print('PASS: two-node capacities, identities, schematics, versions, disks, networking, scheduling and secret exclusions')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        # YAML exceptions can embed secret values. Never echo parser exceptions.
        print('FAIL: ' + (str(error) if isinstance(error, ValueError) and not isinstance(error, yaml.YAMLError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
