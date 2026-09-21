"""Explicitly armed resume of a preserved primary worker after operator shutdown."""
import json
import time
import reconcile as runtime
import consolidate as cluster
import consolidation_policy as policy


def path():return runtime.STATE/'cold-start.json'


def read():return json.loads(path().read_text()) if path().exists() else {}


def save(state):
    tmp=path().with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(path())
    print(json.dumps(state),flush=True)


def owned(identity,node):
    if (node['metadata']['uid']!=identity['uid'] or node['metadata']['name']!=identity['name'] or
        node['spec'].get('providerID')!=runtime.PROVIDER or
        node['status']['nodeInfo']['systemUUID'].lower()!=identity['systemUUID'].lower() or
        'node-role.kubernetes.io/control-plane' in node['metadata'].get('labels',{})):
        raise RuntimeError('Preserved worker identity changed')


def matching_demand(workloads):
    # Deliberately bounded: one primary-pinned Pod in the shared pilot queue.
    # Generic placement remains CA/Kueue's job; unknown demand cannot wake a host here.
    for work in workloads:
        spec=work.get('spec',{});meta=work['metadata']
        if meta.get('namespace')!='prototype-slot' or spec.get('queueName')!='prototype-shared' or not spec.get('active',True):continue
        if any(c['type']=='Finished' and c['status']=='True' for c in work.get('status',{}).get('conditions',[])):continue
        sets=spec.get('podSets',[])
        if len(sets)!=1 or sets[0].get('count')!=1:continue
        template=sets[0]['template'];ps=template['spec']
        if ps.get('nodeSelector')!={'prototype.homelab/pool':'workers','prototype.homelab/slot':'primary'}:continue
        if ps.get('schedulerName')!='homelab-binpack':continue
        if any(ps.get(k) for k in ('affinity','topologySpreadConstraints','initContainers','resources','resourceClaims','overhead','schedulingGates','nodeName')):continue
        if any(set(c.get('resources',{}).get('requests',{}))-set(policy.RESOURCES) for c in ps.get('containers',[])):continue
        if any('persistentVolumeClaim' in v or 'hostPath' in v for v in ps.get('volumes',[])):continue
        requests=policy.requests(template)
        budget={'cpu':'1800m','memory':'3Gi','ephemeral-storage':'15Gi'}
        if all(0<=requests[r]<=policy.quantity(budget[r]) for r in budget) and requests['cpu']>0 and requests['memory']>0:
            return meta['name']
    return None


def resume_worker(identity):
    cluster.check_cluster()
    if (runtime.STATE/'maintenance').exists():raise RuntimeError('Slot is paused')
    owned(identity,cluster.get('node',name=identity['name']))
    runtime.PowerController(runtime.CONFIG,'primary').ensure_on()
    deadline=time.monotonic()+900
    while True:
        try:
            vm=json.loads(runtime.run(runtime.PVE+['inspect']));break
        except (OSError, runtime.subprocess.SubprocessError):
            if time.monotonic()>deadline:raise TimeoutError('Cold PVE readiness deadline')
            time.sleep(10)
    if not vm.get('exists') or vm.get('uuid','').lower()!=identity['systemUUID'].lower():
        raise RuntimeError('Preserved VM generation missing or changed')
    result=json.loads(runtime.run(runtime.PVE+['ensure'],timeout=500))
    if result.get('vmid')!=runtime.VM:raise RuntimeError('Unexpected resumed VM')
    vm=json.loads(runtime.run(runtime.PVE+['inspect']))
    if vm.get('uuid','').lower()!=identity['systemUUID'].lower():raise RuntimeError('VM changed during resume')
    runtime.run(runtime.K+['wait','--for=condition=Ready','node/'+identity['name'],'--timeout=240s'],timeout=260)
    node=cluster.get('node',name=identity['name']);owned(identity,node)
    annotations=dict(node['metadata'].get('annotations',{}))
    if annotations.get(policy.OWNER)==identity['uid']:del annotations[policy.OWNER]
    patch=[{'op':'test','path':'/metadata/uid','value':identity['uid']},
           {'op':'test','path':'/metadata/resourceVersion','value':node['metadata']['resourceVersion']},
           {'op':'add','path':'/metadata/annotations','value':annotations},
           {'op':'add','path':'/spec/unschedulable','value':False}]
    runtime.run(runtime.K+['patch','node',identity['name'],'--type=json','-p',json.dumps(patch)])
    runtime.record('ready',name=identity['name'],ip=result['ip'])


def tick():
    state=read();phase=state.get('phase')
    if phase=='waking':save({**state,'phase':'blocked','error':'interrupted-cold-start'});return True
    if phase=='blocked':return True
    if phase!='armed':return False
    if (runtime.STATE/'maintenance').exists():return True
    demand=matching_demand(cluster.get('workloads'))
    if not demand:return True
    state={**state,'phase':'waking','demand':demand,'startedAt':time.time()};save(state)
    try:
        resume_worker(state)
        save({**state,'phase':'ready','readyAt':time.time()})
    except Exception as exc:
        save({**state,'phase':'blocked','error':type(exc).__name__});raise
    return True
