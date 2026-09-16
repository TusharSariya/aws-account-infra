"""Fresh read-only host checks for the exact worker disk expansion."""
import json
import subprocess
from decimal import Decimal


def verify_host():
    def host(command):
        return json.loads(subprocess.check_output(['ssh', '-o', 'BatchMode=yes', '-o',
            'ConnectTimeout=10', 'server-10-42', command], timeout=30))
    config = host('pvesh get /nodes/pve/qemu/102/config --output-format json')
    if (config['name'] != 'talos-worker-01' or int(config['cores']) != 38
            or int(config['memory']) != 172*1024 or config['hotplug'] != '0'):
        raise ValueError('Unexpected worker identity/settings')
    for key, disk, size in [('scsi0','vm-102-disk-1','100G'),('scsi1','vm-102-disk-2','1200G')]:
        parts=config[key].split(',')
        if parts[0] != 'local-lvm:'+disk or 'size='+size not in parts:
            raise ValueError('Unexpected live worker disk identity/size')
    rows=host('lvs --units b --nosuffix --reportformat json -o vg_name,lv_name,lv_size,segtype,lv_attr,data_percent,metadata_percent')['report'][0]['lv']
    pool=next(x for x in rows if x['vg_name']=='pve' and x['lv_name']=='data')
    if pool['segtype']!='thin-pool' or pool['lv_attr'][4]!='a' or pool['lv_attr'][8]!='-':
        raise ValueError('Physical thin pool unhealthy')
    data,metadata=Decimal(pool['data_percent']),Decimal(pool['metadata_percent'])
    size=Decimal(pool['lv_size'])
    if not all(v.is_finite() for v in (data,metadata,size)) or not 0<=data<70 or not 0<=metadata<70:
        raise ValueError('Physical thin-pool headroom insufficient')
    allocated=sum(Decimal(x['lv_size']) for x in rows if x['vg_name']=='pve' and x['segtype']=='thin')
    if allocated+28*1024**3+64*1024**3>size or size*(1-data/100)<(28+64)*1024**3:
        raise ValueError('Disk growth plus physical headroom does not fit')
    return {'pool_bytes':str(size),'thin_allocated_bytes':str(allocated),
            'pool_data_percent':str(data),'pool_metadata_percent':str(metadata),
            'worker_os_disk':config['scsi0'],'worker_data_disk':config['scsi1']}
