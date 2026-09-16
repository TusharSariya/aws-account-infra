"""Fail closed before allocating cache storage; retained PVs remain commitments."""
import math
import time
from kueue_capacity import quantity


def verify_cache_storage(guest, physical, volumes, config, pvs, now=None):
    now = time.time() if now is None else now
    def sample(values, name, identity):
        item = values[name]
        if (item.get('identity') != identity or item.get('healthy') is not True
                or not 0 <= now - item['measured_at'] <= 90
                or not math.isfinite(item['used_percent']) or not 0 <= item['used_percent'] < 80):
            raise ValueError('Fresh healthy cache capacity below 80% required: ' + name)
        return item
    fs = sample(guest, 'filesystem.bytes', config['filesystemUUID'])
    sample(guest, 'filesystem.inodes', config['filesystemUUID'])
    data = sample(physical, 'pool.data', config['physicalPool'])
    sample(physical, 'pool.metadata', config['physicalPool'])
    if sum(quantity(v['size']) for v in volumes.values()) != 64 * 1024**3:
        raise ValueError('Cache must remain bounded to 64 GiB')
    for name, volume in volumes.items():
        item = sample(guest, 'cache.' + name, str(volume['project']))
        if item['hard_limit_bytes'] != quantity(volume['size']):
            raise ValueError('Actual XFS cache quota differs: ' + name)
    # Include Released/Retain PVs: deleting a claim never frees its data.
    committed = sum(quantity(p['spec']['capacity']['storage']) for p in pvs
                    if p['spec'].get('local', {}).get('path', '').startswith('/var/mnt/local-path-provisioner/'))
    existing = {p['spec'].get('local', {}).get('path') for p in pvs}
    additional = sum(quantity(v['size']) for v in volumes.values()
                     if '/var/mnt/local-path-provisioner/' + v['path'] not in existing)
    total = committed + additional
    # Conservatively reserve all commitments again against free physical space.
    # Do not infer available bytes from thin virtual-disk capacity.
    if total + 8 * 1024**3 > min(fs['available_bytes'], data['available_bytes']):
        raise ValueError('Retained volumes plus cache and physical headroom do not fit')
    return {'committed_bytes': str(total), 'cache_bytes': str(64 * 1024**3),
            'filesystem_available_bytes': fs['available_bytes'], 'thin_pool_available_bytes': data['available_bytes']}
