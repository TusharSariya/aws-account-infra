"""Read-only Proxmox thin-pool sampling. Never accepts an LVM command from a client."""
import json
import math
import subprocess
import time


def parse_lvs(document, pool, measured_at):
    if not isinstance(pool, str) or len(pool.split('/')) != 2:
        raise ValueError('Expected explicit VG/pool identity')
    rows = [row for report in document['report'] for row in report.get('lv', [])
            if row.get('vg_name', '').strip() + '/' + row.get('lv_name', '').strip() == pool]
    if len(rows) != 1 or rows[0].get('segtype', '').strip() != 'thin-pool':
        raise ValueError('Expected exactly one named thin pool')
    row = rows[0]
    attr = row.get('lv_attr', '').strip()
    # LVM attribute positions: thin-pool, active, normal health at position 9.
    if len(attr) < 9 or attr[0] != 't' or attr[4] != 'a' or attr[8] != '-':
        raise ValueError('Thin pool is not active and healthy')
    result = {}
    for name, key in [('pool.data', 'data_percent'), ('pool.metadata', 'metadata_percent')]:
        value = float(row[key])
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError('Invalid thin-pool percentage')
        result[name] = {'identity': pool, 'healthy': True, 'measured_at': measured_at, 'used_percent': value}
    return result


def collect(pool):
    result = subprocess.run(['/usr/sbin/lvs', '--reportformat', 'json',
                             '--options', 'vg_name,lv_name,segtype,lv_attr,data_percent,metadata_percent'],
                            capture_output=True, text=True, timeout=10, check=True,
                            env={'PATH': '/usr/sbin:/usr/bin', 'LC_ALL': 'C'})
    return parse_lvs(json.loads(result.stdout), pool, time.time())


def main():
    from pathlib import Path
    import os
    config = json.loads(Path('/etc/homelab-capacity/config.json').read_text())
    try:
        sample = collect(config['pool'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        sample = {name: {'identity': config['pool'], 'healthy': False,
                         'measured_at': time.time(), 'used_percent': None}
                  for name in ('pool.data', 'pool.metadata')}
    target = Path('/run/homelab-capacity/sample.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(sample, allow_nan=False))
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)


if __name__ == '__main__':
    main()
