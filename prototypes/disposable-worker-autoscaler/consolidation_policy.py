"""Conservative prototype policy. Unsupported constraints block movement."""
from decimal import Decimal
import re
import os

def configured_idle_seconds(value):
    if not str(value).isascii() or not str(value).isdecimal() or int(value)<=0:
        raise ValueError('HOMELAB_IDLE_SECONDS must be a positive integer')
    return int(value)


IDLE_SECONDS = configured_idle_seconds(os.environ.get('HOMELAB_IDLE_SECONDS','1800'))
POLICY = 'prototype.homelab/policy'
MOVE = 'prototype.homelab/allow-move'
OWNER = 'prototype.homelab/consolidation-owner'
NAMESPACE = 'prototype-consolidation'
IDENTITIES = {'primary':'proxmox://prototype-primary/9107',
              'secondary':'proxmox://prototype-secondary/9105'}
RESOURCES = ('cpu','memory','ephemeral-storage')
BASELINE_DAEMONSETS = {('kube-system','cilium'),('kube-system','cilium-envoy'),
                      ('kube-system','kube-proxy'),('prototype-connectivity','peer'),
                      ('prototype105-csi','prototype105-csi-proxmox-csi-plugin-node')}


def quantity(value):
    text=str(value)
    suffix=re.search(r'(Ki|Mi|Gi|Ti|Pi|Ei|[numkKMGTPE])$',text)
    unit=suffix.group() if suffix else ''
    number=Decimal(text[:-len(unit)] if unit else text)
    binary={x+'i':Decimal(1024)**i for i,x in enumerate('KMGTPE',1)}
    decimal={'n':Decimal('1e-9'),'u':Decimal('1e-6'),'m':Decimal('1e-3'),
             'k':Decimal(1000),'K':Decimal(1000),**{x:Decimal(1000)**i for i,x in enumerate('MGTPE',2)}}
    result=number*(binary.get(unit,decimal.get(unit,Decimal(1))))
    if not result.is_finite() or result<0:raise ValueError('Negative resource quantity')
    return result


def active(pod):
    return pod.get('status',{}).get('phase') not in ('Succeeded','Failed')


def baseline(pod):
    return any(o.get('kind')=='DaemonSet' and (pod['metadata']['namespace'],o['name']) in BASELINE_DAEMONSETS
               for o in pod['metadata'].get('ownerReferences',[]))


def requests(pod):
    spec=pod['spec'];total={r:Decimal(0) for r in RESOURCES}
    # Sum init requests as well: conservative for sidecars/complex init ordering.
    for c in spec.get('containers',[])+spec.get('initContainers',[]):
        for r in RESOURCES:total[r]+=quantity(c.get('resources',{}).get('requests',{}).get(r,0))
    for r in RESOURCES:
        total[r]=max(total[r],quantity(spec.get('resources',{}).get('requests',{}).get(r,0)))
        total[r]+=quantity(spec.get('overhead',{}).get(r,0))
    return total


def ready(node):
    return any(c['type']=='Ready' and c['status']=='True' for c in node.get('status',{}).get('conditions',[]))


def selected_nodes(nodes):
    found={}
    for node in nodes:
        for slot,identity in IDENTITIES.items():
            if node['spec'].get('providerID')==identity:
                if slot in found:raise ValueError('Duplicate owned provider identity')
                if 'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels',{}):
                    raise ValueError('Refusing control-plane identity')
                found[slot]=node
    return found


def demand(pods,workloads):
    reasons=[]
    for p in pods:
        if active(p) and not p['spec'].get('nodeName') and not baseline(p):
            reasons.append('pending-pod:'+p['metadata']['namespace']+'/'+p['metadata']['name'])
    for w in workloads:
        conditions={c['type']:c['status'] for c in w.get('status',{}).get('conditions',[])}
        if conditions.get('Finished')!='True' and conditions.get('Admitted')!='True' and w.get('spec',{}).get('active',True):
            reasons.append('queued-workload:'+w['metadata']['name'])
    return reasons


def matches(labels,selector):
    if selector is None:return False
    if any(labels.get(k)!=v for k,v in selector.get('matchLabels',{}).items()):return False
    for e in selector.get('matchExpressions',[]):
        key=e['key'];op=e['operator'];values=e.get('values',[])
        if op=='In' and labels.get(key) not in values:return False
        if op=='NotIn' and key in labels and labels[key] in values:return False
        if op=='Exists' and key not in labels:return False
        if op=='DoesNotExist' and key in labels:return False
        if op not in ('In','NotIn','Exists','DoesNotExist'):raise ValueError('Unknown selector operator')
    return True


def movement_blockers(pod,pdbs):
    meta=pod['metadata'];spec=pod['spec'];a=meta.get('annotations',{})
    policy=a.get(POLICY,'experimental');reasons=[]
    if policy not in ('scheduled','on-invoke','persistent','experimental'):reasons.append('invalid-policy')
    if policy=='persistent':reasons.append('persistent')
    if any(o['kind']=='Job' for o in meta.get('ownerReferences',[])):reasons.append('active-job')
    if meta['namespace']!=NAMESPACE:reasons.append('outside-pilot-scope')
    if a.get(MOVE)!='true':reasons.append('movement-not-permitted')
    owners=[o for o in meta.get('ownerReferences',[]) if o.get('controller')]
    if len(owners)!=1 or owners[0]['kind']!='ReplicaSet':reasons.append('unsupported-owner')
    if meta.get('deletionTimestamp'):reasons.append('terminating')
    if any('persistentVolumeClaim' in v or 'hostPath' in v for v in spec.get('volumes',[])):reasons.append('persistent-or-host-storage')
    if any(set(v)-{'name','emptyDir','configMap','secret','projected','downwardAPI'} for v in spec.get('volumes',[])):reasons.append('unsupported-volume')
    if any(spec.get(k) for k in ('affinity','topologySpreadConstraints','resourceClaims','schedulingGates','initContainers','resources','overhead')):reasons.append('unsupported-scheduling')
    if spec.get('hostNetwork') or any(p.get('hostPort') for c in spec.get('containers',[]) for p in c.get('ports',[])):reasons.append('host-network-or-port')
    for c in spec.get('containers',[]):
        req=c.get('resources',{}).get('requests',{})
        if not {'cpu','memory'}<=set(req) or set(req)-set(RESOURCES):reasons.append('unsupported-resource-request')
    for pdb in pdbs:
        if pdb['metadata']['namespace']==meta['namespace'] and matches(meta.get('labels',{}),pdb['spec'].get('selector')):
            st=pdb.get('status',{})
            if st.get('observedGeneration')!=pdb['metadata'].get('generation') or st.get('disruptionsAllowed',0)<1:
                reasons.append('pdb:'+pdb['metadata']['name'])
    return sorted(set(reasons))


def plan(nodes,pods,workloads,pdbs,source='primary',destination='secondary'):
    owned=selected_nodes(nodes);blocks=demand(pods,workloads)
    if source==destination or source not in owned or destination not in owned:
        return {'allowed':False,'blockers':['missing-or-identical-slots'],'moves':[]}
    src,dst=owned[source],owned[destination]
    if not ready(src) or not ready(dst) or dst['spec'].get('unschedulable'):blocks.append('node-unavailable')
    if src['spec'].get('unschedulable') and src['metadata'].get('annotations',{}).get(OWNER)!=src['metadata']['uid']:
        blocks.append('foreign-cordon')
    if any(t.get('effect') in ('NoSchedule','NoExecute') for t in dst['spec'].get('taints',[])):blocks.append('destination-taint')
    candidates=[p for p in pods if p['spec'].get('nodeName')==src['metadata']['name'] and active(p) and not baseline(p)]
    residents=[p for p in pods if p['spec'].get('nodeName')==dst['metadata']['name'] and active(p)]
    available={r:quantity(dst['status']['allocatable'].get(r,0))-sum((requests(p)[r] for p in residents),Decimal(0)) for r in RESOURCES}
    pod_slots=int(dst['status']['allocatable']['pods'])-len(residents)
    moves=[]
    for p in candidates:
        identity=p['metadata']['namespace']+'/'+p['metadata']['name']
        blocks.extend(identity+':'+reason for reason in movement_blockers(p,pdbs))
        if any(dst['metadata'].get('labels',{}).get(k)!=v for k,v in p['spec'].get('nodeSelector',{}).items()):blocks.append(identity+':selector-mismatch')
        req=requests(p)
        for r in RESOURCES:available[r]-=req[r]
        pod_slots-=1
        moves.append({'namespace':p['metadata']['namespace'],'name':p['metadata']['name'],'uid':p['metadata']['uid']})
    if any(v<0 for v in available.values()) or pod_slots<0:blocks.append('destination-insufficient-capacity')
    return {'allowed':not blocks,'blockers':sorted(set(blocks)),'moves':moves,
            'source':src['metadata']['name'],'sourceUID':src['metadata']['uid'],
            'destination':dst['metadata']['name'],'destinationUID':dst['metadata']['uid']}


def idle_transition(previous,uid,now,eligible,new_demand=False,committed=False):
    if committed or (previous.get('uid')==uid and previous.get('phase')=='shutdown-committed'):
        return {'uid':uid,'phase':'shutdown-committed','rewakeQueued':bool(new_demand or previous.get('rewakeQueued')),'cancelShutdown':False}
    if not eligible or new_demand:
        return {'uid':uid,'phase':'active','idleSince':None,'cancelShutdown':bool(new_demand),'rewakeQueued':False}
    since=previous.get('idleSince') if previous.get('uid')==uid else None
    if (since is None or since>now or now-previous.get('lastObserved',now)>45 or
        previous.get('idleSeconds')!=IDLE_SECONDS):since=now
    return {'uid':uid,'phase':'retirement-eligible' if now-since>=IDLE_SECONDS else 'idle',
            'idleSince':since,'idleSeconds':IDLE_SECONDS,'lastObserved':now,'deadline':since+IDLE_SECONDS,'cancelShutdown':False,'rewakeQueued':False}
