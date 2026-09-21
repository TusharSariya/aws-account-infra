#!/usr/bin/env python3
"""Explicit retirement of the isolated slot; no automatic idle policy or host power-off."""
import argparse
import fcntl
import json
import time
from reconcile import STATE, PROTOTYPE, K, PVE, PROVIDER, run, record



def owned_node(node, name, uid):
    if (node['metadata']['name'] != name or node['metadata']['uid'] != uid or
        node['spec'].get('providerID') != PROVIDER or
        'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels', {})):
        raise RuntimeError('Refusing foreign/replaced/control-plane node')


def retire(name, uid):
    cfg=json.loads(run(K+['config','view','--minify','-o','json']))['clusters'][0]
    if cfg['name']!='laptop-wifi-PROTOTYPE' or cfg['cluster']['server']!='https://10.0.2.15:6443':
        raise RuntimeError('Not the isolated prototype cluster')
    with (STATE/'lifecycle.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if json.loads((STATE/'desired.json').read_text())['target']!=1:
            raise RuntimeError('Expected one owned worker')
        node=json.loads(run(K+['get','node',name,'-o','json']))
        owned_node(node,name,uid)
        vm=json.loads(run(PVE+['inspect']))
        if not vm['exists'] or not vm.get('uuid'):
            raise RuntimeError('Expected existing VM generation')
        addresses=[a['address'] for a in node['status'].get('addresses',[]) if a['type']=='InternalIP']
        if (addresses != [vm['ip']] or
            node['status']['nodeInfo'].get('systemUUID','').lower() != vm['uuid'].lower()):
            raise RuntimeError('Node/VM address or hardware generation mismatch')
        record('draining',name=name,uid=uid,vm_uuid=vm['uuid'])
        run(K+['drain',name,'--ignore-daemonsets','--delete-emptydir-data','--timeout=60s'],timeout=80)
        deadline=time.monotonic()+120
        while True:
            attachments=json.loads(run(K+['get','volumeattachments','-o','json']))['items']
            if not any(v['spec']['nodeName']==name for v in attachments):break
            if time.monotonic()>deadline:raise TimeoutError('Retained volume detach deadline')
            time.sleep(2)
        owned_node(json.loads(run(K+['get','node',name,'-o','json'])),name,uid)
        record('stopping',name=name,uid=uid,vm_uuid=vm['uuid'])
        run([str(PROTOTYPE/'talosctl'),'--talosconfig',str(PROTOTYPE/'private/talosconfig'),'--endpoints','10.0.2.15','--nodes',vm['ip'],'shutdown','--wait=false'])
        deadline=time.monotonic()+180
        while True:
            current=json.loads(run(PVE+['inspect']))
            if current.get('uuid')!=vm['uuid']:raise RuntimeError('VM generation changed')
            if current['status']=='stopped':break
            if time.monotonic()>deadline:raise TimeoutError('Graceful stop deadline')
            time.sleep(3)
        # Recheck storage immediately before the host's independent disk ownership guard.
        attachments=json.loads(run(K+['get','volumeattachments','-o','json']))['items']
        if any(v['spec']['nodeName']==name for v in attachments):raise RuntimeError('Attachment reappeared')
        result=json.loads(run(PVE+['retire '+vm['uuid']],timeout=180))
        if result.get('retired_uuid')!=vm['uuid'] or result.get('status')!='absent':
            raise RuntimeError('Unexpected retirement result')
        owned_node(json.loads(run(K+['get','node',name,'-o','json'])),name,uid)
        run(K+['delete','node',name])
        tmp=STATE/'desired.tmp';tmp.write_text('{"target":0}\n');tmp.replace(STATE/'desired.json')
        record('retired',name=name,uid=uid,vm_uuid=vm['uuid'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--node',required=True);p.add_argument('--uid',required=True)
    a=p.parse_args()
    try:
        retire(a.node,a.uid)
    except Exception as exc:
        print(json.dumps({"phase":"retirement-failed", "name":a.node, "error":type(exc).__name__}), flush=True)
        raise
