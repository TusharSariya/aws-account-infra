"""Create fixed core-v1 acceptance fixtures with strict server-side validation.

Bypass kubectl's OpenAPI discovery, not server validation or admission.
https://kubernetes.io/docs/reference/using-api/api-concepts/#field-validation
"""
import argparse
import json
import os
import re
import subprocess
import sys
import yaml

RESOURCES = {'Namespace': 'namespaces', 'Pod': 'pods', 'Service': 'services',
             'PersistentVolumeClaim': 'persistentvolumeclaims', 'ResourceQuota': 'resourcequotas'}


def create(kubectl, value, *, dry_run=False):
    if value.get('apiVersion') != 'v1' or value.get('kind') not in RESOURCES:
        raise ValueError('Only fixed core-v1 acceptance fixtures are supported')
    path = '/api/v1/'
    if value['kind'] != 'Namespace':
        namespace = value['metadata']['namespace']
        if not re.fullmatch(r'(?:storage-check|homelab-network-check)-[a-z0-9-]+', namespace):
            raise ValueError('Disposable acceptance namespace required')
        path += 'namespaces/' + namespace + '/'
    else:
        name = value['metadata'].get('name', value['metadata'].get('generateName', ''))
        if not re.fullmatch(r'(?:storage-check|homelab-network-check)-[a-z0-9-]*', name):
            raise ValueError('Disposable acceptance namespace required')
    path += RESOURCES[value['kind']] + '?fieldValidation=Strict'
    if dry_run:
        path += '&dryRun=All'
    return subprocess.run([kubectl, '--request-timeout=30s', 'create', '--raw', path, '-f', '-'],
                          input=json.dumps(value), capture_output=True, text=True, timeout=40)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--namespace')
    parser.add_argument('--name', action='store_true')
    args = parser.parse_args()
    for value in yaml.safe_load_all(sys.stdin):
        if args.namespace:
            if value['metadata'].get('namespace', args.namespace) != args.namespace:
                raise ValueError('Fixture namespace mismatch')
            value['metadata']['namespace'] = args.namespace
        result = create(os.environ.get('KUBECTL', 'kubectl'), value)
        if result.returncode:
            raise ValueError('Strict server fixture creation failed')
        if args.name:
            print(json.loads(result.stdout)['metadata']['name'])


if __name__ == '__main__':
    main()
