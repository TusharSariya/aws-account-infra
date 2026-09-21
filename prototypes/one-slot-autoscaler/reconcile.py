#!/usr/bin/env python3
"""Scale-up-only prototype reconciler. No production VM or shutdown operations."""
import json
import os
import fcntl
from pathlib import Path
import subprocess
import time
from homelab_capacity.imm2 import PowerController

HOME = Path.home()
SLOT = os.environ.get('HOMELAB_PROTOTYPE_SLOT','secondary')
if SLOT not in ('primary','secondary'):raise RuntimeError('Unknown prototype slot')
VM = 9107 if SLOT=='primary' else 9105
PROVIDER = f'proxmox://prototype-{SLOT}/{VM}'
STATE = HOME/'.local/share/homelab-capacity'/('slot-primary' if SLOT=='primary' else 'slot-state')
PROTOTYPE = HOME/'talos-wifi-prototype'
CONFIG = HOME/'.config/homelab-capacity/hosts.json'
K = [str(PROTOTYPE/'kubectl'),'--kubeconfig',str(PROTOTYPE/'private/kubeconfig'),'--request-timeout=10s']
PVE = ['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','UserKnownHostsFile='+str(HOME/'.config/homelab-capacity/pve_known_hosts'),'-i',str(HOME/'.config/homelab-capacity/pve_slot'),'root@'+('10.0.0.224' if SLOT=='primary' else '10.0.0.223')]


def run(args, timeout=30):
    return subprocess.check_output(args,timeout=timeout).decode()


def record(phase, **fields):
    tmp=STATE/'observed.tmp'
    tmp.write_text(json.dumps({'phase':phase,**fields}));tmp.replace(STATE/'observed.json')
    print(json.dumps({'phase':phase,**fields}),flush=True)


def storage_ready(pods, drivers):
    return bool(pods) and all(
        any(c['type']=='Ready' and c['status']=='True' for c in p.get('status',{}).get('conditions',[]))
        for p in pods
    ) and any(d['name']=='csi.proxmox.sinextra.dev' for d in drivers)


def wait_talos(ip):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            run([str(PROTOTYPE/'talosctl'), '--nodes', ip, 'version', '--insecure'], timeout=10)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            time.sleep(2)
    raise TimeoutError('Talos maintenance API readiness deadline')


def reconcile():
    # This cluster check runs before any mutation, including host wake.
    cfg=json.loads(run(K+['config','view','--minify','-o','json']))
    if cfg['clusters'][0]['name']!='laptop-wifi-PROTOTYPE' or cfg['clusters'][0]['cluster']['server']!='https://10.0.2.15:6443':
        raise RuntimeError('Not the isolated prototype cluster')
    record('waking')
    PowerController(CONFIG,SLOT).ensure_on()
    record('waiting-pve')
    deadline=time.monotonic()+600
    while True:
        try:
            json.loads(run(PVE+['inspect']));break
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            if time.monotonic()>deadline:raise TimeoutError('PVE readiness deadline')
            time.sleep(10)
    record('creating')
    result=json.loads(run(PVE+['ensure'],timeout=500))
    if result.get('vmid')!=VM:raise RuntimeError('Unexpected VM identity')
    ip=result['ip']
    # The address is derived from a DHCP ACK for the fixed prototype MAC by the host helper.
    import ipaddress
    if ipaddress.ip_address(ip) not in ipaddress.ip_network('10.0.0.0/24'):raise RuntimeError('Unexpected guest address')
    record('configuring',ip=ip)
    nodes=json.loads(run(K+['get','nodes','-o','json']))['items']
    matching=[n for n in nodes if any(a['type']=='InternalIP' and a['address']==ip for a in n['status'].get('addresses',[]))]
    if not matching:
        record('waiting-talos',ip=ip)
        wait_talos(ip)
        run([str(PROTOTYPE/'talosctl'),'apply-config','--insecure','--nodes',ip,'--file',str(PROTOTYPE/'private/peer.yaml')],timeout=120)
    record('joining',ip=ip)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        nodes=json.loads(run(K+['get','nodes','-o','json']))['items']
        matches=[n for n in nodes if any(a['type']=='InternalIP' and a['address']==ip for a in n['status'].get('addresses',[]))]
        if matches:
            node=matches[0];name=node['metadata']['name']
            if 'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels',{}):raise RuntimeError('Refusing control-plane node')
            existing=node['spec'].get('providerID','')
            if existing not in ('',PROVIDER):raise RuntimeError('Foreign provider identity')
            run(K+['patch','node',name,'--type=merge','-p',json.dumps({'spec':{'providerID':PROVIDER}})])
            run(K+['label','node',name,'--overwrite','prototype.homelab/csi-worker='+str(SLOT=='secondary').lower(),'topology.kubernetes.io/region=prototype-'+SLOT,'topology.kubernetes.io/zone=pve'])
            run(K+['wait','--for=condition=Ready','node/'+name,'--timeout=180s'],timeout=200)
            if SLOT=='secondary':
                record('waiting-csi',name=name,ip=ip)
                csi_deadline=time.monotonic()+180
                while time.monotonic()<csi_deadline:
                    pods=json.loads(run(K+['-n','prototype105-csi','get','pods','--field-selector','spec.nodeName='+name,'-o','json']))['items']
                    csi=run(K+['get','csinode',name,'--ignore-not-found','-o','json']).strip()
                    drivers=json.loads(csi)['spec'].get('drivers',[]) if csi else []
                    if storage_ready(pods,drivers):break
                    time.sleep(2)
                else:raise TimeoutError('CSI registration/readiness deadline')
            # Publish workload eligibility only after all worker prerequisites pass.
            run(K+['label','node',name,'--overwrite','prototype.homelab/slot='+SLOT,'prototype.homelab/pool=workers','prototype.homelab/stateless-only='+str(SLOT=='primary').lower()])
            record('ready',name=name,ip=ip);return
        time.sleep(5)
    raise TimeoutError('Fresh node join deadline')


if __name__=='__main__':
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    while True:
        if (STATE/'desired.json').exists() and json.loads((STATE/'desired.json').read_text())['target']==1:
            try:
                with (STATE/"lifecycle.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    if json.loads((STATE/"desired.json").read_text())["target"] != 1:
                        continue
                    reconcile()
            except Exception as exc:
                record('failed',error=type(exc).__name__)
                raise
            # One proof transition; leave the running VM for explicit inspection.
            break
        time.sleep(2)
