import copy
import json
import subprocess
import pytest
import consolidation_policy as p
import consolidate as actor


def node(slot):
    return {'metadata':{'name':slot,'uid':slot+'-uid','resourceVersion':'1','labels':{'pool':'workers'}},
            'spec':{'providerID':p.IDENTITIES[slot]},
            'status':{'conditions':[{'type':'Ready','status':'True'}],
                      'allocatable':{'cpu':'2','memory':'4Gi','ephemeral-storage':'15Gi','pods':'110'}}}


def pod(name='app',host='primary'):
    return {'metadata':{'name':name,'namespace':p.NAMESPACE,'uid':name+'-uid','resourceVersion':'1','labels':{'app':name},
                        'annotations':{p.POLICY:'on-invoke',p.MOVE:'true'},
                        'ownerReferences':[{'kind':'ReplicaSet','name':'app-rs','uid':'rs-uid','controller':True}]},
            'spec':{'nodeName':host,'nodeSelector':{'pool':'workers'},
                    'containers':[{'resources':{'requests':{'cpu':'500m','memory':'128Mi','ephemeral-storage':'64Mi'}}}]},
            'status':{'phase':'Running'}}


def snapshot():return {'nodes':[node('primary'),node('secondary')],'pods':[pod()], 'workloads':[], 'pdbs':[]}


def test_fit_counts_destination_residents_and_all_candidates():
    s=snapshot();assert p.plan(**s)['allowed']
    s['pods'] += [pod('busy','secondary')]
    s['pods'][1]['spec']['containers'][0]['resources']['requests']['cpu']='1800m'
    assert 'destination-insufficient-capacity' in p.plan(**s)['blockers']


@pytest.mark.parametrize('change,reason',[
    (lambda x:x['metadata']['annotations'].update({p.POLICY:'persistent'}),'persistent'),
    (lambda x:x['metadata']['annotations'].pop(p.MOVE),'movement-not-permitted'),
    (lambda x:x['metadata']['ownerReferences'][0].update(kind='Job'),'active-job'),
    (lambda x:x['spec'].update(volumes=[{'name':'data','persistentVolumeClaim':{'claimName':'data'}}]),'persistent-or-host-storage'),
    (lambda x:x['spec'].update(affinity={'nodeAffinity':{}}),'unsupported-scheduling'),
    (lambda x:x['spec']['containers'][0]['resources']['requests'].update({'vendor/gpu':'1'}),'unsupported-resource-request'),
])
def test_policy_blocks_unsafe_movement(change,reason):
    x=pod();change(x);assert reason in p.movement_blockers(x,[])


def test_pdb_unknown_stale_or_no_budget_blocks():
    pdb={'metadata':{'name':'protect','namespace':p.NAMESPACE,'generation':2},
         'spec':{'selector':{'matchLabels':{'app':'app'}}},'status':{'observedGeneration':1,'disruptionsAllowed':1}}
    assert p.movement_blockers(pod(),[pdb])==['pdb:protect']
    pdb['status']={'observedGeneration':2,'disruptionsAllowed':0}
    assert p.movement_blockers(pod(),[pdb])==['pdb:protect']
    pdb['status']['disruptionsAllowed']=1
    assert p.movement_blockers(pod(),[pdb])==[]


def test_pending_demand_and_foreign_cordon_block():
    s=snapshot();s['pods'].append(pod('pending',''))
    assert not p.plan(**s)['allowed']
    s=snapshot();s['nodes'][0]['spec']['unschedulable']=True
    assert 'foreign-cordon' in p.plan(**s)['blockers']
    s['nodes'][0]['metadata']['annotations']={p.OWNER:'primary-uid'}
    assert p.plan(**s)['allowed']
    s['workloads']=[{'metadata':{'name':'queued'},'spec':{}}]
    assert 'queued-workload:queued' in p.plan(**s)['blockers']


def test_duplicate_provider_identity_is_rejected():
    s=snapshot();s['nodes'].append(copy.deepcopy(s['nodes'][0]))
    with pytest.raises(ValueError):p.plan(**s)


def test_30_minute_window_is_single_persisted_timer():
    state={}
    for now in range(100,1900,10):
        state=p.idle_transition(state,'uid',now,True)
        assert state['phase']=='idle' and state['idleSince']==100
        state=json.loads(json.dumps(state))
    assert p.idle_transition(state,'uid',1900,True)['phase']=='retirement-eligible'
    canceled=p.idle_transition(state,'uid',1900,True,new_demand=True)
    assert canceled['cancelShutdown'] and canceled['idleSince'] is None
    assert p.idle_transition(canceled,'uid',1910,True)['idleSince']==1910


def test_generation_clock_and_observer_gaps_restart_timer():
    old=p.idle_transition({},'old',100,True)
    assert p.idle_transition(old,'new',110,True)['idleSince']==110
    assert p.idle_transition(old,'old',90,True)['idleSince']==90
    assert p.idle_transition(old,'old',2000,True)['idleSince']==2000


def test_post_commit_demand_is_durably_queued_not_cancellation():
    state=p.idle_transition({},'uid',100,True,committed=True,new_demand=True)
    assert state['rewakeQueued'] and not state['cancelShutdown']
    assert p.idle_transition(state,'uid',110,False)['rewakeQueued']


def test_evict_rejection_has_no_delete_fallback(monkeypatch):
    calls=[]
    def reject(args,**kwargs):
        calls.append((args,json.loads(kwargs['input'])))
        raise subprocess.CalledProcessError(1,args)
    monkeypatch.setattr(actor.subprocess,'run',reject)
    with pytest.raises(subprocess.CalledProcessError):actor.evict(pod())
    assert len(calls)==1 and '/eviction' in calls[0][0][-3]
    assert calls[0][1]['deleteOptions']['preconditions']=={'uid':'app-uid','resourceVersion':'1'}


def test_reopen_only_own_cordon_with_atomic_identity_tests(monkeypatch):
    calls=[];monkeypatch.setattr(actor,'run',lambda args:calls.append(args))
    n=node('primary');n['spec']['unschedulable']=True
    assert not actor.cordon(n,False) and not calls
    n['metadata']['annotations']={p.OWNER:'primary-uid'}
    assert actor.cordon(n,False)
    patch=json.loads(calls[0][-1])
    assert patch[:2]==[{'op':'test','path':'/metadata/uid','value':'primary-uid'},
                       {'op':'test','path':'/metadata/resourceVersion','value':'1'}]
    assert patch[-1]['value'] is False


@pytest.mark.parametrize('bad',['NaN','Infinity','-1'])
def test_invalid_resources_fail_closed(bad):
    with pytest.raises((ValueError,ArithmeticError)):p.quantity(bad)


def test_failed_eviction_reopens_own_node(monkeypatch):
    from contextlib import nullcontext
    s=snapshot();n=s['nodes'][0];changes=[]
    monkeypatch.setattr(actor,'check_cluster',lambda:None)
    monkeypatch.setattr(actor,'locked',nullcontext)
    monkeypatch.setattr(actor,'snapshot',lambda:s)
    monkeypatch.setattr(actor,'get',lambda resource,namespace=None,name=None: n if resource=='node' else s['pods'][0])
    monkeypatch.setattr(actor,'cordon',lambda node,enabled:changes.append(enabled))
    monkeypatch.setattr(actor,'deployment_owner',lambda pod:'rs-uid')
    def reject(pod):raise RuntimeError('PDB rejection')
    monkeypatch.setattr(actor,'evict',reject)
    with pytest.raises(RuntimeError,match='PDB rejection'):actor.apply('primary','secondary')
    assert changes==[True,False]


def test_replaced_pod_is_not_evicted(monkeypatch):
    from contextlib import nullcontext
    s=snapshot();changed=copy.deepcopy(s['pods'][0]);changed['metadata']['resourceVersion']='2'
    calls=[]
    monkeypatch.setattr(actor,'check_cluster',lambda:None)
    monkeypatch.setattr(actor,'locked',nullcontext)
    monkeypatch.setattr(actor,'snapshot',lambda:s)
    monkeypatch.setattr(actor,'get',lambda resource,namespace=None,name=None:s['nodes'][0] if resource=='node' else changed)
    monkeypatch.setattr(actor,'cordon',lambda node,enabled:None)
    monkeypatch.setattr(actor,'evict',lambda pod:calls.append(pod))
    with pytest.raises(RuntimeError,match='Pod changed'):actor.apply('primary','secondary')
    assert not calls


def test_other_cluster_is_refused(monkeypatch):
    monkeypatch.setattr(actor,'run',lambda _:json.dumps({'clusters':[{'name':'production','cluster':{'server':'https://10.0.2.15:6443'}}]}))
    with pytest.raises(RuntimeError,match='Not the isolated'):actor.check_cluster()


def test_stale_annotation_on_schedulable_node_cannot_start_idle(monkeypatch,tmp_path):
    from contextlib import nullcontext
    s=snapshot();s['pods']=[]
    s['nodes'][0]['metadata']['annotations']={p.OWNER:'primary-uid'}
    monkeypatch.setattr(actor,'STATE',tmp_path)
    monkeypatch.setattr(actor,'check_cluster',lambda:None)
    monkeypatch.setattr(actor,'locked',nullcontext)
    monkeypatch.setattr(actor,'snapshot',lambda:s)
    monkeypatch.setattr(actor,'get',lambda _:[])
    result=actor.observe()
    assert result['primary']['phase']=='active'
    assert 'not-controller-cordoned' in result['primary']['blockers']


@pytest.mark.parametrize('value',['0','-1','five','1.5','Infinity',''])
def test_idle_configuration_rejects_invalid_windows(value):
    with pytest.raises(ValueError):p.configured_idle_seconds(value)


def test_changed_window_restarts_timer_and_five_minutes_is_exact(monkeypatch):
    previous=p.idle_transition({},'uid',100,True)
    monkeypatch.setattr(p,'IDLE_SECONDS',p.configured_idle_seconds('300'))
    state=p.idle_transition(previous,'uid',110,True)
    assert state['idleSince']==110 and state['deadline']==410
    for now in range(120,410,10):
        state=p.idle_transition(state,'uid',now,True)
        assert state['phase']=='idle'
    assert p.idle_transition(state,'uid',410,True)['phase']=='retirement-eligible'
