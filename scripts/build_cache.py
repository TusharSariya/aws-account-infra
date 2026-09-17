"""Scope disposable registry caches independently of trusted release images."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path


def cache_run_prefix():
    if os.environ.get('HOMELAB_DEPENDENCY_CACHE') != '1':
        return 'RUN '
    return ('RUN --network=host --mount=type=secret,id=dependency-env,required=true '
            '--mount=type=secret,id=dependency-apt,required=true '
            'set -a; . /run/secrets/dependency-env; set +a; ')

BUILDKIT_IMAGE = 'moby/buildkit@sha256:28a898719c18a33f4e8000685287fa36fd0dd9560c6440227d3a732d79bb41d8'  # v0.32.2
REGISTRY = 'nexus.homelab-cache.svc.cluster.local:5003'
MIRRORS = {'docker.io': 5000, 'ghcr.io': 5001, 'public.ecr.aws': 5002, 'mcr.microsoft.com': 5004}


def registry_config():
    config = '[registry."' + REGISTRY + '"]\n  http = true\n'
    for origin, port in MIRRORS.items():
        mirror = 'nexus.homelab-cache.svc.cluster.local:' + str(port)
        config += ('[registry."' + origin + '"]\n  mirrors = ["' + mirror + '"]\n'
                   '[registry."' + mirror + '"]\n  http = true\n')
    return config


def key(value):
    readable = re.sub('[^a-z0-9]+', '-', value.lower()).strip('-')[:48] or 'scope'
    return readable + '-' + hashlib.sha256(value.encode()).hexdigest()[:12]


def pod_cgroup_parent():
    uid = os.environ.get('HOMELAB_RUNNER_POD_UID', '')
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', uid):
        raise ValueError('Observed Talos Pod UID required')
    parent = Path('/var/run/homelab-pod-cgroup').read_text().strip()
    if parent != '/kubepods/pod' + uid:
        raise ValueError('BuildKit must share the admitted runner Pod cgroup')
    return parent


def settings(workflow, platform, branch, *, cgroup_parent=None):
    if platform not in ('linux/amd64', 'linux/arm64'):
        raise ValueError('One reviewed build platform required')
    if not workflow or not branch:
        raise ValueError('Workflow and branch scope required')
    if cgroup_parent is not None and not re.fullmatch(
            r'/kubepods/pod[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', cgroup_parent):
        raise ValueError('Exact guaranteed Talos Pod cgroup required')
    repository = REGISTRY + '/ci/' + key(workflow) + '/' + platform.replace('/', '-')
    current = repository + ':' + key(branch)
    main = repository + ':' + key('main')
    return {
        'cache-from': '\n'.join('type=registry,ref=' + ref for ref in dict.fromkeys([current, main])),
        'cache-to': 'type=registry,ref=' + current + ',mode=max,oci-mediatypes=true,image-manifest=true,ignore-error=true',
        'config': registry_config(),
        'driver-opts': 'network=host\nimage=' + BUILDKIT_IMAGE +
                       ('\ncgroup-parent=' + cgroup_parent if cgroup_parent else ''),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow', required=True)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--branch', required=True)
    args = parser.parse_args()
    print(json.dumps(settings(args.workflow, args.platform, args.branch)))
