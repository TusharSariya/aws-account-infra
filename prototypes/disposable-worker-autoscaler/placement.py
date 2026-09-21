#!/usr/bin/env python3
"""Publish advisory expansion preferences; never changes power or deletes workloads."""
import argparse
import json
import subprocess
import time
from reconcile import K, CONFIG
from homelab_capacity.imm2 import PowerController, PowerError


def priorities(states):
    # Existing Ready-node fit is handled by CA before expansion. Among eligible
    # new groups prefer known-on hosts, then known-off; unknown is never assumed off.
    rank={'on':200,'off':100,'unknown':1}
    return {f'prototype-{slot}':rank[states[slot]]+(10 if slot=='secondary' else 0)
            for slot in ('primary','secondary')}


def publish():
    cfg=json.loads(subprocess.check_output(K+['config','view','--minify','-o','json']))['clusters'][0]
    if cfg['name']!='laptop-wifi-PROTOTYPE' or cfg['cluster']['server']!='https://10.0.2.15:6443':
        raise RuntimeError('Not the isolated prototype cluster')
    states={}
    for slot in ('primary','secondary'):
        try:states[slot]=PowerController(CONFIG,slot).get_power().power
        except PowerError:states[slot]='unknown'
    ranks=priorities(states)
    data=''.join(f'{rank}:\n  - ^{group}$\n' for group,rank in ranks.items())
    doc={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'cluster-autoscaler-priority-expander','namespace':'prototype-slot'},'data':{'priorities':data}}
    subprocess.run(K+['apply','-f','-'],input=json.dumps(doc).encode(),check=True,timeout=30)
    print(json.dumps({'power':states,'priorities':ranks}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--once',action='store_true');a=p.parse_args()
    while True:
        publish()
        if a.once:break
        time.sleep(30)
