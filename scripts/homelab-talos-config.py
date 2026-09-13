#!/usr/bin/env python3
"""Generate local Talos recovery inputs; never contacts a node or applies config."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/environments/proxmox/homelab/talos'
sys.path.insert(0, str(ROOT / "scripts"))
from talos_tools import VERSION, cli, private_dir


def run(binary, args, diagnostic):
    # Parser errors may include secret configuration lines. Keep diagnostics private.
    with diagnostic.open('ab') as stream:
        result = subprocess.run([str(binary), *map(str, args)], stdout=stream, stderr=stream)
    if result.returncode:
        raise ValueError(f'talosctl failed; inspect private diagnostics at {diagnostic}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init-secrets', 'generate'])
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.config/aws-account-infra/talos/homelab')
    parser.add_argument('--output', type=Path, help='New, empty output directory outside the checkout (generate only)')
    args = parser.parse_args()
    os.umask(0o077)
    state = private_dir(args.state_dir)
    secrets = state / 'talos-secrets.yaml'
    binary = cli()
    if args.action == 'init-secrets':
        if secrets.exists() or secrets.is_symlink():
            raise ValueError('Secrets already exist; reuse or restore them, never recreate for an existing cluster')
        run(binary, ['gen', 'secrets', '--talos-version', VERSION, '-o', secrets], state / 'init.log')
        print(f'Created cluster secrets at {secrets}. Encrypted independent backup is still required.')
        return
    if not secrets.is_file() or secrets.is_symlink():
        raise ValueError('Restore the cluster secrets bundle or explicitly run init-secrets for a new cluster')
    if secrets.stat().st_uid != os.getuid() or secrets.stat().st_mode & 0o077:
        raise ValueError('Secrets must be owned by this user with mode 0600')
    if not args.output:
        raise ValueError('generate requires --output pointing to a new directory')
    output = private_dir(args.output)
    if any(output.iterdir()):
        raise ValueError('Output directory must be empty; existing configs are never overwritten')
    inventory = json.loads((CONFIG / 'cluster.json').read_text())
    diagnostic = output / 'generation.log'
    for node in inventory['nodes']:
        staging = output / node['name']
        staging.mkdir(mode=0o700)
        run(binary, ['gen', 'config', inventory['name'], inventory['endpoint'],
                     '--talos-version', VERSION, '--kubernetes-version', inventory['kubernetes_version'],
                     '--install-disk', '/dev/sda', '--install-image', node['installer'],
                     '--with-secrets', secrets, '--with-docs=false', '--with-examples=false',
                     '--output-types', node['type'] + (',talosconfig' if node['type'] == 'controlplane' else ''),
                     '--config-patch', '@' + str(CONFIG / 'patches/common.yaml'),
                     '--config-patch', '@' + str(CONFIG / ('patches/' + node['name'] + '.yaml')),
                     '--output', staging if node['type'] == 'controlplane' else staging / 'worker.yaml'], diagnostic)
        generated = staging / (node['type'] + '.yaml')
        run(binary, ['validate', '--config', generated, '--mode', 'metal', '--strict'], diagnostic)
        generated.rename(output / (node['name'] + '.machineconfig.yaml'))
        if node['type'] == 'controlplane':
            talosconfig = staging / 'talosconfig'
            run(binary, ['--talosconfig', talosconfig, 'config', 'endpoint', inventory['talos_endpoint']], diagnostic)
            run(binary, ['--talosconfig', talosconfig, 'config', 'node', inventory['talos_endpoint']], diagnostic)
            talosconfig.rename(output / 'talosconfig')
        staging.rmdir()
    print(f"Generated and strictly validated {len(inventory['nodes'])} machine configs in {output}. No node contacted.")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
