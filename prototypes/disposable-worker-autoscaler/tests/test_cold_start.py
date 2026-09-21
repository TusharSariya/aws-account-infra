import json
from types import SimpleNamespace
import pytest
import cold_start as cold
import capacity_control as control
from test_idle_lifecycle import env

UUID='01234567-89ab-cdef-0123-456789abcdef'


def workload():
    return {'metadata':{'namespace':'prototype-slot','name':'test'},'spec':{'queueName':'prototype-shared',
        'podSets':[{'count':1,'template':{'spec':{'schedulerName':'homelab-binpack',
        'nodeSelector':{'prototype.homelab/pool':'workers','prototype.homelab/slot':'primary'},
        'containers':[{'resources':{'requests':{'cpu':'1000m','memory':'128Mi','ephemeral-storage':'64Mi'}}}]}}}]}}


@pytest.mark.parametrize('change', ['secondary','unfit','many','finished','inactive','foreign-queue','storage','affinity'])
def test_only_matching_fitting_pilot_demand_can_wake(change):
    w=workload();spec=w['spec']['podSets'][0]['template']['spec']
    assert cold.matching_demand([w])=='test'
    if change=='secondary':spec['nodeSelector']['prototype.homelab/slot']='secondary'
    if change=='unfit':spec['containers'][0]['resources']['requests']['cpu']='2'
    if change=='many':w['spec']['podSets'][0]['count']=2
    if change=='finished':w['status']={'conditions':[{'type':'Finished','status':'True'}]}
    if change=='inactive':w['spec']['active']=False
    if change=='foreign-queue':w['spec']['queueName']='other'
    if change=='storage':spec['volumes']=[{'name':'data','persistentVolumeClaim':{'claimName':'data'}}]
    if change=='affinity':spec['affinity']={'nodeAffinity':{}}
    assert cold.matching_demand([w]) is None


def identity(env):
    data,*_=env
    data['node']['status']['nodeInfo']={'systemUUID':UUID}
    return {'name':'primary','uid':'primary-uid','systemUUID':UUID,'phase':'armed'}


def test_pause_blocks_wake_even_with_queued_demand(env,monkeypatch):
    state=identity(env);cold.save(state);env[0]['workloads']=[workload()]
    (env[2]/'maintenance').touch()
    monkeypatch.setattr(cold,'resume_worker',lambda _:pytest.fail('Paused'))
    assert cold.tick()
    assert cold.read()['phase']=='armed'


def test_armed_empty_queue_does_not_boot(env,monkeypatch):
    cold.save(identity(env))
    monkeypatch.setattr(cold,'resume_worker',lambda _:pytest.fail('No demand'))
    assert cold.tick() and cold.read()['phase']=='armed'


def test_matching_queue_starts_once(env,monkeypatch):
    cold.save(identity(env));env[0]['workloads']=[workload()];calls=[]
    monkeypatch.setattr(cold,'resume_worker',lambda state:calls.append(state))
    assert cold.tick();assert not cold.tick()
    assert len(calls)==1 and calls[0]['demand']=='test'
    assert cold.read()['phase']=='ready'


def test_interrupted_or_failed_wake_requires_review(env,monkeypatch):
    cold.save({**identity(env),'phase':'waking'})
    monkeypatch.setattr(cold,'resume_worker',lambda _:pytest.fail('No retry'))
    assert cold.tick() and cold.read()['phase']=='blocked'
    assert cold.tick()


def test_node_change_blocks_before_power_action(env,monkeypatch):
    state=identity(env);env[0]['node']['metadata']['uid']='changed'
    monkeypatch.setattr(cold.runtime,'PowerController',lambda *a:pytest.fail('No power action'))
    with pytest.raises(RuntimeError,match='identity changed'):cold.resume_worker(state)


@pytest.mark.parametrize('vm_uuid',[UUID,'changed'])
def test_preserved_vm_generation_checked_before_start(env,monkeypatch,vm_uuid):
    state=identity(env);calls=[]
    monkeypatch.setattr(cold.runtime,'PowerController',lambda *a:SimpleNamespace(ensure_on=lambda:calls.append('power-on')))
    def run(args,**kw):
        calls.append(args)
        if args[-1]=='inspect':return json.dumps({'exists':True,'uuid':vm_uuid})
        if args[-1]=='ensure':return '{"vmid":9107,"ip":"10.0.0.11"}'
        return ''
    monkeypatch.setattr(cold.runtime,'VM',9107)
    monkeypatch.setattr(cold.runtime,'run',run)
    monkeypatch.setattr(cold.runtime,'record',lambda *a,**kw:None)
    if vm_uuid!=UUID:
        with pytest.raises(RuntimeError,match='VM generation'):cold.resume_worker(state)
        assert not any(isinstance(c,list) and c[-1]=='ensure' for c in calls)
    else:
        cold.resume_worker(state)
        patch=next(json.loads(c[-1]) for c in calls if isinstance(c,list) and 'patch' in c)
        assert patch[0]['value']=='primary-uid' and patch[-1]['value'] is False


def test_explicit_resume_arms_without_waking_and_keeps_secondary_paused(env,monkeypatch):
    data,_,slot,obs=env
    base=slot.parent;(base/'slot-primary').mkdir();(base/'slot-state').mkdir()
    monkeypatch.setattr(control.cluster,'BASE',base)
    monkeypatch.setattr(control.runtime,'STATE',base/'slot-primary')
    (control.runtime.STATE/'desired.json').write_text('{"target":1}')
    (control.runtime.STATE/'maintenance').touch();(base/'slot-state/maintenance').touch()
    data['node']['status']['nodeInfo']={'systemUUID':UUID}
    data['nodes']=[data['node']]
    monkeypatch.setattr(control.runtime,'PowerController',lambda *a:SimpleNamespace(get_power=lambda:SimpleNamespace(power='off')))
    result=control.control('resume',['primary'])
    assert result['mode']=='wait-for-matching-demand'
    assert cold.read()['phase']=='armed'
    assert not (control.runtime.STATE/'maintenance').exists()
    assert (base/'slot-state/maintenance').exists()


def test_reconcile_cannot_bypass_pause(env,monkeypatch):
    (env[2]/'maintenance').touch()
    monkeypatch.setattr(cold.runtime,'PowerController',lambda *a:pytest.fail('No wake'))
    with pytest.raises(RuntimeError,match='paused'):cold.runtime.reconcile()


def test_pause_is_all_or_nothing_when_a_slot_is_busy(env,monkeypatch):
    import fcntl
    base=env[2].parent
    for name in ('slot-primary','slot-state'):(base/name).mkdir()
    monkeypatch.setattr(control.cluster,'BASE',base)
    with (base/'slot-state/lifecycle.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):control.control('pause',['primary','secondary'])
    assert not (base/'slot-primary/maintenance').exists()
    assert not (base/'slot-state/maintenance').exists()


def test_failed_resume_blocks_retry(env,monkeypatch):
    cold.save(identity(env));env[0]['workloads']=[workload()]
    def fail(state):raise TimeoutError('Unknown wake result')
    monkeypatch.setattr(cold,'resume_worker',fail)
    with pytest.raises(TimeoutError):cold.tick()
    monkeypatch.setattr(cold,'resume_worker',lambda _:pytest.fail('No retry'))
    assert cold.tick() and cold.read()['phase']=='blocked'


def test_generation_change_during_resume_never_uncordons(env,monkeypatch):
    state=identity(env);calls=[];generation=iter([UUID,'changed'])
    monkeypatch.setattr(cold.runtime,'VM',9107)
    monkeypatch.setattr(cold.runtime,'PowerController',lambda *a:SimpleNamespace(ensure_on=lambda:None))
    def run(args,**kw):
        calls.append(args)
        if args[-1]=='inspect':return json.dumps({'exists':True,'uuid':next(generation)})
        if args[-1]=='ensure':return '{"vmid":9107,"ip":"10.0.0.11"}'
        raise AssertionError('No node mutation after generation changed')
    monkeypatch.setattr(cold.runtime,'run',run)
    with pytest.raises(RuntimeError,match='VM changed during resume'):cold.resume_worker(state)
    assert not any('patch' in c for c in calls)


def test_observer_does_not_reopen_paused_node_on_demand(env,monkeypatch):
    from contextlib import nullcontext
    from test_consolidation import snapshot,pod
    observer=control.cluster;base=env[2].parent
    (base/'slot-primary').mkdir();(base/'slot-primary/maintenance').touch()
    monkeypatch.setattr(observer,'BASE',base)
    s=snapshot();s['nodes'][0]['spec']['unschedulable']=True
    s['nodes'][0]['metadata']['annotations']={cold.policy.OWNER:'primary-uid'}
    s['pods']=[pod('queued','')]
    monkeypatch.setattr(observer,'locked',nullcontext)
    monkeypatch.setattr(observer,'snapshot',lambda:s)
    monkeypatch.setattr(observer,'get',lambda _:[])
    monkeypatch.setattr(observer,'cordon',lambda n,on:False if n['metadata']['name']=='secondary' else pytest.fail('Paused primary reopened'))
    result=observer.observe()
    assert 'maintenance' in result['primary']['blockers'] and not result['primary']['reopened']
