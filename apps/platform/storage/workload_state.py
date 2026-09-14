"""Conservative observation of retained terminal Pods; missing state is active."""


def is_terminated(pod):
    status, spec = pod.get('status', {}), pod.get('spec', {})
    if status.get('phase') not in ('Succeeded', 'Failed'):
        return False
    expected = {container['name'] for field in ('containers', 'initContainers', 'ephemeralContainers')
                for container in spec.get(field, [])}
    states = {container['name']: container.get('state', {}) for field in
              ('containerStatuses', 'initContainerStatuses', 'ephemeralContainerStatuses')
              for container in status.get(field, [])}
    return bool(expected) and all('exitCode' in states.get(name, {}).get('terminated', {}) for name in expected)
