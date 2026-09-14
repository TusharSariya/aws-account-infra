#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Issue separate capacity identities into a new private directory outside Git."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def issue(directory):
    directory = directory.expanduser().resolve()
    if (directory == ROOT or ROOT in directory.parents or directory.exists()
            or any((parent / '.git').exists() for parent in directory.parents)):
        raise ValueError('A new directory outside the repository is required')
    config = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml').read_text())
    address = str(ipaddress.ip_network(config['physicalAddress'], strict=True).network_address)
    if config['config']['physicalURL'] != 'https://' + address + ':9443/capacity':
        raise ValueError('The reviewed numeric endpoint must match the egress address')
    if not any(ipaddress.ip_address(address) in ipaddress.ip_network(cidr)
               for cidr in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10')):
        raise ValueError('Private capacity endpoint required')
    os.umask(0o077)
    directory.mkdir(mode=0o700, parents=True)

    def run(*args):
        result = subprocess.run(args, cwd=directory, capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Credential issuance failed; private diagnostics suppressed')

    for purpose, eku in [('server', 'serverAuth'), ('client', 'clientAuth')]:
        ca, leaf = purpose + '-ca', purpose
        run('openssl', 'req', '-new', '-x509', '-newkey', 'ed25519', '-noenc',
            '-keyout', ca + '.key', '-out', ca + '.crt', '-days', '1825',
            '-subj', '/CN=homelab-capacity-' + ca,
            '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('openssl', 'req', '-new', '-newkey', 'ed25519', '-noenc',
            '-keyout', leaf + '.key', '-out', leaf + '.csr', '-subj', '/CN=homelab-capacity-' + leaf)
        extensions = 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=' + eku + '\n'
        if purpose == 'server':
            extensions += 'subjectAltName=IP:' + address + '\n'
        (directory / (leaf + '.ext')).write_text(extensions)
        run('openssl', 'x509', '-req', '-in', leaf + '.csr', '-CA', ca + '.crt',
            '-CAkey', ca + '.key', '-CAcreateserial', '-days', '365',
            '-extfile', leaf + '.ext', '-out', leaf + '.crt')
        run('openssl', 'verify', '-CAfile', ca + '.crt', '-purpose',
            'sslserver' if purpose == 'server' else 'sslclient', leaf + '.crt')
    run('openssl', 'verify', '-CAfile', 'server-ca.crt', '-verify_ip', address, 'server.crt')
    run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'homelab-capacity-ci', '-f', 'ci-host-ed25519')

    def bundle(name, contents):
        (directory / name).write_bytes(base64.b64encode(json.dumps(contents).encode()))

    read = lambda name: (directory / name).read_text()
    bundle('host-credentials.b64', {'config.json': json.dumps({'bind': address, 'pool': config['config']['physicalPool']}),
                                  'server.crt': read('server.crt'), 'server.key': read('server.key'),
                                  'client-ca.crt': read('client-ca.crt')})
    bundle('client-credentials.b64', {'ca.crt': read('server-ca.crt'),
                                    'tls.crt': read('client.crt'), 'tls.key': read('client.key')})
    print('PASS: separate CA, client, server and administrative SSH identities issued and verified')
    print('Leaf certificates expire after 365 days. Securely retain CA keys separately; no offline backup is claimed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    issue(args.output)
