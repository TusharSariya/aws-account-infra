#!/usr/bin/env python3
"""Run as root on SECONDARY PVE only. Fixed prototype IDs, no general deletion."""
import argparse
import json
import re
import subprocess

OLD, NEW = 9103, 9104
ISO = 'local:iso/PROTOTYPE-talos-v1.13.9-metal.iso'
def command(*args):
    return subprocess.check_output(args, timeout=180).decode()
def api(path):
    return json.loads(command('pvesh', 'get', path, '--output-format', 'json'))
def config(vmid):
    return api(f'/nodes/pve/qemu/{vmid}/config')
def volumes():
    return api('/nodes/pve/storage/local-lvm/content')
def present(volid):
    return any(v['volid'] == volid for v in volumes())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['inspect-delete', 'delete-old', 'create-new'])
    p.add_argument('--retained-volume', required=True)
    a=p.parse_args()
    # This script is transported only over the pinned secondary host SSH identity.
    assert re.fullmatch(r'local-lvm:vm-9199-[A-Za-z0-9_.-]+',a.retained_volume), 'Expected reserved CSI test-volume owner9199'
    assert present(a.retained_volume), 'Retained test volume is absent'
    if a.action=='create-new':
        assert not any(v['vmid']==NEW for v in api('/nodes/pve/qemu')), 'Replacement ID already exists'
        print(command('qm','create',str(NEW),'--name','PROTOTYPE-storage-replacement','--memory','4096','--cores','2','--cpu','host','--onboot','0','--scsihw','virtio-scsi-single','--scsi0','local-lvm:24','--ide2',ISO+',media=cdrom','--net0','virtio=52:54:00:77:03:04,bridge=vmbr0','--boot','order=scsi0;ide2','--description','Disposable storage reattachment prototype105. Never production.'))
        print(command('qm','start',str(NEW)))
        return
    c=config(OLD)
    assert c.get('name')=='PROTOTYPE-wifi-peer', 'Unexpected VM identity'
    assert api(f'/nodes/pve/qemu/{OLD}/status/current')['status']=='stopped', 'Guest must be cleanly stopped first'
    disks={}
    for key,value in c.items():
        if not re.fullmatch(r'(?:scsi|virtio|sata|ide|unused)\d+|efidisk0|tpmstate0',key):
            continue
        if key=='ide2' and value.split(',')[0]==ISO and 'media=cdrom' in value:
            continue
        volid=value.split(',')[0]
        assert re.fullmatch(r'local-lvm:vm-9103-disk-\d+',volid), f'Non-disposable disk reference blocks deletion: {key}'
        disks[key]=volid
    assert disks, 'No recognized disposable disks'
    print(json.dumps({'vmid':OLD,'owned_disposable_disks':disks,'retained_volume':a.retained_volume,'action':a.action},indent=2),flush=True)
    if a.action=='delete-old':
        print(command('qm','destroy',str(OLD),'--purge','0','--destroy-unreferenced-disks','0'))
        assert present(a.retained_volume), 'Retained volume unexpectedly missing after delete'
        print('Retained volume still present after VM deletion',flush=True)

if __name__=='__main__':
    main()
