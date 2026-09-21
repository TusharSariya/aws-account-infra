#!/usr/bin/python3
"""Forced-command helper for secondary PVE. Owns prototype IDs9105/9106; can retire only stopped, disk-guarded VM9105."""
import fcntl
import json
import os
import re
import shlex
from pathlib import Path
import socket
import struct
import subprocess
import time

# Root-owned selection; the SSH caller cannot choose a host or arbitrary VM ID.
HOST_CONFIG = Path('/etc/prototype-slot.json')
SLOT = json.loads(HOST_CONFIG.read_text())['slot'] if HOST_CONFIG.exists() else 'secondary'
if SLOT not in ('primary','secondary'):raise RuntimeError('Unknown prototype slot')
VM, TEMPLATE = (9107,9108) if SLOT=='primary' else (9105,9106)
MAC = bytes.fromhex('525400770307' if SLOT=='primary' else '525400770305')
NAME = 'PROTOTYPE-autoscaler-primary' if SLOT=='primary' else 'PROTOTYPE-autoscaler-slot'
TNAME = 'PROTOTYPE-autoscaler-primary-template' if SLOT=='primary' else 'PROTOTYPE-autoscaler-empty-template'
ISO = 'local:iso/PROTOTYPE-talos-v1.13.9-metal.iso'
STATE = Path('/var/lib/prototype-slot')


def run(*args):
    return subprocess.check_output(args, timeout=180, stderr=subprocess.STDOUT).decode()


def vms():
    return json.loads(run('pvesh','get','/nodes/pve/qemu','--output-format','json'))


def checked(vmid, name):
    found = next((x for x in vms() if x['vmid'] == vmid), None)
    if found and found['name'] != name:
        raise RuntimeError('Unexpected pre-existing VM identity')
    return found


def dhcp_ack(path):
    if not path.exists(): return None
    raw=path.read_bytes()
    if len(raw)<24: return None
    endian='<' if raw[:4]==b'\xd4\xc3\xb2\xa1' else '>'
    pos=24
    while pos+16<=len(raw):
        size=struct.unpack(endian+'IIII',raw[pos:pos+16])[2];pos+=16
        if pos+size>len(raw): break
        packet=raw[pos:pos+size];pos+=size
        if len(packet)<42 or packet[12:14]!=b'\x08\x00':continue
        ihl=(packet[14]&15)*4
        bootp=packet[14+ihl+8:]
        if len(bootp)<240 or bootp[28:34]!=MAC:continue
        options=bootp[240:];i=0;ack=False
        while i<len(options):
            code=options[i];i+=1
            if code==255:break
            if code==0:continue
            if i>=len(options):break
            length=options[i];i+=1
            value=options[i:i+length];i+=length
            if code==53 and value==b'\x05':ack=True
        if ack:return socket.inet_ntoa(bootp[16:20])
    return None


def ensure_csi_access():
    # PVE removes per-VM ACLs when a disposable guest is destroyed. Restore both
    # sides of the privilege-separated token on every ensure, before readiness.
    if SLOT=='primary':return  # Primary pilot advertises stateless capacity only.
    run('pveum','acl','modify','/vms/9105','--roles','Prototype105Disk',
        '--users','prototype105-csi@pve')
    run('pveum','acl','modify','/vms/9105','--roles','Prototype105Disk',
        '--tokens','prototype105-csi@pve!csi')


def disposable_config(cfg, expected_uuid):
    if (cfg.get('name') != NAME or
        cfg.get('description') != 'Owner one-slot-proof. Disposable prototype only. Never production.' or
        cfg.get('smbios1') != 'uuid=' + expected_uuid or cfg.get('onboot') != 0):
        raise RuntimeError('VM ownership/generation mismatch')
    disks = {k: v.split(',')[0] for k, v in cfg.items()
             if re.fullmatch(r'(scsi|sata|ide|virtio|unused|efidisk|tpmstate)\d+', k)}
    if disks != {'scsi0': f'local-lvm:vm-{VM}-disk-0', 'ide2': ISO}:
        raise RuntimeError('Unexpected or retained disk reference blocks retirement')
    if cfg.get('lock') or cfg.get('template'):
        raise RuntimeError('Locked/template VM blocks retirement')


def retire(expected_uuid):
    cfg = json.loads(run('pvesh','get',f'/nodes/pve/qemu/{VM}/config','--output-format','json'))
    disposable_config(cfg, expected_uuid)
    status = json.loads(run('pvesh','get',f'/nodes/pve/qemu/{VM}/status/current','--output-format','json'))
    if status['status'] != 'stopped':
        raise RuntimeError('Only a gracefully stopped VM can be retired')
    run('qm','destroy',str(VM),'--purge','0','--destroy-unreferenced-disks','0')
    if checked(VM, NAME):raise RuntimeError('VM still exists after destroy')
    print(json.dumps({'vmid': VM, 'status': 'absent', 'retired_uuid': expected_uuid}))


def main():
    args=shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND',''))
    if args in (['inspect'], ['ensure']):
        action=args[0]
    elif len(args)==2 and args[0]=='retire' and re.fullmatch(r'[0-9a-f-]{36}',args[1]):
        action='retire'
    else:
        raise RuntimeError('Only inspect, ensure or generation-bound retire allowed')
    STATE.mkdir(mode=0o700,exist_ok=True)
    with (STATE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=checked(VM,NAME)
        if action=='retire':
            retire(args[1]);return
        if action=='inspect':
            ip=dhcp_ack(STATE/'dhcp.pcap')
            print(json.dumps({'exists':bool(old),'status':old['status'] if old else 'absent','ip':ip,'uuid':json.loads(run('pvesh','get',f'/nodes/pve/qemu/{VM}/config','--output-format','json')).get('smbios1','').removeprefix('uuid=') if old else None}));return
        if not checked(TEMPLATE,TNAME):
            run('qm','create',str(TEMPLATE),'--name',TNAME,'--memory','4096','--cores','2','--cpu','host','--onboot','0','--scsihw','virtio-scsi-single','--scsi0','local-lvm:24','--ide2',ISO+',media=cdrom','--net0','virtio,bridge=vmbr0','--boot','order=scsi0;ide2','--description','Prototype empty OS template; no installed identity. Owner one-slot-proof.')
            run('qm','template',str(TEMPLATE))
        if not old:
            run('qm','clone',str(TEMPLATE),str(VM),'--full','1','--name',NAME)
            run('qm','set',str(VM),'--net0','virtio='+':'.join(f'{b:02x}' for b in MAC)+',bridge=vmbr0','--onboot','0','--description','Owner one-slot-proof. Disposable prototype only. Never production.')
            old=checked(VM,NAME)
        ensure_csi_access()
        if old['status']=='stopped':
            pcap=STATE/'dhcp.pcap'
            proc=subprocess.Popen(['tcpdump','-ni','vmbr0','-U','-w',str(pcap),f'udp src port 67 and udp dst port 68 and udp[36:4] = 0x{MAC[:4].hex()} and udp[40:2] = 0x{MAC[4:].hex()}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.3)
                if proc.poll() is not None:raise RuntimeError('DHCP capture failed')
                run('qm','start',str(VM))
                deadline=time.monotonic()+240
                while time.monotonic()<deadline:
                    ip=dhcp_ack(pcap)
                    if ip:break
                    time.sleep(2)
                else:raise TimeoutError('No DHCP ACK observed for prototype MAC')
            finally:
                proc.terminate();proc.wait(timeout=5)
        ip=dhcp_ack(STATE/'dhcp.pcap')
        if not ip:raise RuntimeError('Running VM address unknown; inspect rather than restart')
        print(json.dumps({'vmid':VM,'ip':ip,'status':'running'}))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error':str(e)}));raise SystemExit(1)
