#!/usr/bin/env python3
"""Explicit pilot eviction plus an idle observer. Never retires VMs or powers hosts off."""
import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import json
from pathlib import Path
import subprocess
import time
from reconcile import K, run
import consolidation_policy as policy

BASE = Path.home()/'.local/share/homelab-capacity'
STATE = BASE/'consolidation'


def check_cluster():
    cfg=json.loads(run(K+['config','view','--minify','-o','json']))['clusters'][0]
    if cfg['name']!='laptop-wifi-PROTOTYPE' or cfg['cluster']['server']!='https://10.0.2.15:6443':
        raise RuntimeError('Not the isolated prototype cluster')


def get(resource, namespace=None, name=None):
    args=K+(['-n',namespace] if namespace else [])+['get',resource]
    if name:args.append(name)
    elif namespace is None and resource in ('pods','workloads','poddisruptionbudgets'):args.append('-A')
    doc=json.loads(run(args+['-o','json']))
    return doc if name else doc['items']


def snapshot():
    return {key:get(resource) for key,resource in
            [('nodes','nodes'),('pods','pods'),('workloads','workloads'),('pdbs','poddisruptionbudgets')]}


@contextmanager
def locked():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with ExitStack() as stack:
        for path in [STATE/'controller.lock',BASE/'slot-primary/lifecycle.lock',BASE/'slot-state/lifecycle.lock']:
            lock=stack.enter_context(path.open('a'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def cordon(node, enabled):
    meta=node['metadata'];uid=meta['uid'];annotations=dict(meta.get('annotations',{}))
    owner=annotations.get(policy.OWNER)
    if enabled:
        if owner not in (None,uid) or (node['spec'].get('unschedulable') and owner!=uid):
            raise RuntimeError('Refusing foreign cordon')
        annotations[policy.OWNER]=uid
    else:
        if owner!=uid:return False
        del annotations[policy.OWNER]
    patch=[{'op':'test','path':'/metadata/uid','value':uid},
           {'op':'test','path':'/metadata/resourceVersion','value':meta['resourceVersion']},
           {'op':'add','path':'/metadata/annotations','value':annotations},
           {'op':'add','path':'/spec/unschedulable','value':enabled}]
    run(K+['patch','node',meta['name'],'--type=json','-p',json.dumps(patch)])
    return True


def deployment_owner(pod):
    owner=next(o for o in pod['metadata']['ownerReferences'] if o.get('controller'))
    rs=get('replicaset',pod['metadata']['namespace'],owner['name'])
    owners=[o for o in rs['metadata'].get('ownerReferences',[]) if o.get('controller')]
    if rs['metadata']['uid']!=owner['uid'] or len(owners)!=1 or owners[0]['kind']!='Deployment':
        raise RuntimeError('ReplicaSet is not owned by a Deployment')
    deployment=get('deployment',pod['metadata']['namespace'],owners[0]['name'])
    if deployment['metadata']['uid']!=owners[0]['uid'] or deployment['metadata'].get('deletionTimestamp'):
        raise RuntimeError('Deployment changed or terminating')
    return owner['uid']


def evict(pod):
    m=pod['metadata']
    eviction={'apiVersion':'policy/v1','kind':'Eviction','metadata':{'name':m['name'],'namespace':m['namespace']},
              'deleteOptions':{'preconditions':{'uid':m['uid'],'resourceVersion':m['resourceVersion']}}}
    subprocess.run(K+['create','--raw',f"/api/v1/namespaces/{m['namespace']}/pods/{m['name']}/eviction",'-f','-'],
                   input=json.dumps(eviction).encode(),check=True,timeout=30,stdout=subprocess.PIPE)


def apply(source,destination):
    check_cluster()
    with locked():
        initial=policy.plan(**snapshot(),source=source,destination=destination)
        if not initial['allowed']:raise RuntimeError(json.dumps(initial))
        src=get('node',name=initial['source'])
        if (src['metadata']['uid']!=initial['sourceUID'] or
            src['spec'].get('providerID')!=policy.IDENTITIES[source]):raise RuntimeError('Source replaced')
        cordon(src,True)
        try:
            for move in initial['moves']:
                current=snapshot();decision=policy.plan(**current,source=source,destination=destination)
                if (not decision['allowed'] or decision['sourceUID']!=initial['sourceUID'] or
                    decision['destinationUID']!=initial['destinationUID']):raise RuntimeError(json.dumps(decision))
                pod=get('pod',move['namespace'],move['name'])
                observed=next((p for p in current['pods'] if p['metadata']['uid']==move['uid']),None)
                if (pod['metadata']['uid']!=move['uid'] or observed is None or
                    pod['metadata']['resourceVersion']!=observed['metadata']['resourceVersion']):
                    raise RuntimeError('Pod changed since capacity check')
                if pod['spec'].get('nodeName')!=initial['source'] or policy.movement_blockers(pod,current['pdbs']):
                    raise RuntimeError('Pod policy or placement changed')
                rs_uid=deployment_owner(pod)
                before={p['metadata']['uid'] for p in current['pods']}
                evict(pod)
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    pods=get('pods',move['namespace'])
                    replacements=[p for p in pods if p['metadata']['uid'] not in before and
                        any(o.get('controller') and o['uid']==rs_uid for o in p['metadata'].get('ownerReferences',[]))]
                    if (not any(p['metadata']['uid']==move['uid'] for p in pods) and
                        any(p['spec'].get('nodeName')==initial['destination'] and policy.ready(p) for p in replacements)):break
                    time.sleep(2)
                else:raise TimeoutError('Replacement readiness deadline')
            print(json.dumps({'phase':'consolidated',**initial}),flush=True)
        except BaseException:
            current=get('node',name=initial['source'])
            if current['metadata']['uid']==initial['sourceUID']:cordon(current,False)
            raise


def observe():
    check_cluster()
    with locked():
        current=snapshot();pending=policy.demand(current['pods'],current['workloads'])
        attachments=get('volumeattachments');owned=policy.selected_nodes(current['nodes'])
        path=STATE/'idle.json';previous=json.loads(path.read_text()) if path.exists() else {}
        report={}
        for slot,node in owned.items():
            m=node['metadata'];name=m['name'];uid=m['uid']
            reopened=cordon(node,False) if pending else False
            blockers=[]
            if not policy.ready(node):blockers.append('node-not-ready')
            if any(policy.active(p) and p['spec'].get('nodeName')==name and not policy.baseline(p) for p in current['pods']):blockers.append('active-workloads')
            if any(v['spec']['nodeName']==name for v in attachments):blockers.append('volume-attachments')
            if (m.get('annotations',{}).get(policy.OWNER)!=uid or
                not node['spec'].get('unschedulable') or reopened):blockers.append('not-controller-cordoned')
            blockers.extend(pending)
            state=policy.idle_transition(previous.get(slot,{}),uid,time.time(),not blockers,bool(pending))
            report[slot]={**state,'node':name,'reopened':reopened,'blockers':blockers,
                          'physicalPowerOffEnabled':False,'shutdownBlockers':['production-host-services-not-migrated','automatic-retirement-disabled']}
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,indent=2)+'\n');tmp.replace(path)
        print(json.dumps(report),flush=True)
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','apply','observe'))
    parser.add_argument('--source',choices=tuple(policy.IDENTITIES),default='primary')
    parser.add_argument('--destination',choices=tuple(policy.IDENTITIES),default='secondary')
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    if args.action=='plan':
        check_cluster();print(json.dumps(policy.plan(**snapshot(),source=args.source,destination=args.destination),indent=2))
    elif args.action=='apply':apply(args.source,args.destination)
    else:
        while True:
            try:observe()
            except BlockingIOError:pass  # Another lifecycle action owns the lock; retry next tick.
            if not args.watch:break
            time.sleep(10)


if __name__=='__main__':main()
