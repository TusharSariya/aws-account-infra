"""Lease election plus durable runtime fencing before any command or reconciliation."""
from copy import deepcopy
from datetime import datetime, timezone
import time

from kube import Conflict, Unavailable

LEASE_PATH = '/apis/coordination.k8s.io/v1/namespaces/homelab-platform/leases/ai-lifecycle'
LEASE_SECONDS = 20


class Leadership:
    def __init__(self, api, identity):
        self.api, self.identity = api, identity
        self.valid_until = 0

    def renew(self):
        self.valid_until = 0
        started = time.monotonic()
        lease = self.api.call('GET', LEASE_PATH)
        spec = lease.get('spec', {})
        now = datetime.now(timezone.utc)
        try:
            renewed = datetime.fromisoformat(spec.get('renewTime', '').replace('Z', '+00:00'))
            expired = (now - renewed).total_seconds() > spec.get('leaseDurationSeconds', LEASE_SECONDS)
        except (ValueError, TypeError):
            expired = not spec.get('holderIdentity')
        if spec.get('holderIdentity') not in ('', None, self.identity) and not expired:
            return False
        value = deepcopy(lease)
        value['spec'] = {**spec, 'holderIdentity': self.identity, 'leaseDurationSeconds': LEASE_SECONDS,
                         'renewTime': now.isoformat(timespec='microseconds').replace('+00:00', 'Z')}
        if spec.get('holderIdentity') != self.identity:
            value['spec']['leaseTransitions'] = spec.get('leaseTransitions', 0) + 1
            value['spec']['acquireTime'] = value['spec']['renewTime']
        try:
            self.api.put(LEASE_PATH, value)
        except (Conflict, Unavailable):
            return False
        # Reserve enough time for a single bounded API write before expiry.
        self.valid_until = started + LEASE_SECONDS - 6
        return self.active()

    def active(self):
        return time.monotonic() < self.valid_until

    def fence(self, runtime, state):
        if not self.active():
            raise Unavailable('Lifecycle leader is unavailable')
        if state['owner'] != self.identity:
            raise Conflict('Runtime belongs to another leadership generation')
