import json
import pytest
import idle_lifecycle as lifecycle
import consolidation_policy as policy
from test_consolidation import node,pod


@pytest.fixture
def env(monkeypatch,tmp_path):
    slot=tmp_path/'slot';slot.mkdir();obs=tmp_path/'observer';obs.mkdir()
    monkeypatch.setattr(lifecycle.runtime,'STATE',slot)
    monkeypatch.setattr(lifecycle.runtime,'SLOT','primary')
    monkeypatch.setattr(lifecycle.runtime,'PROVIDER',policy.IDENTITIES['primary'])
    monkeypatch.setattr(lifecycle.observer,'STATE',obs)
    monkeypatch.setattr(lifecycle.observer,'check_cluster',lambda:None)
    monkeypatch.setattr(lifecycle.time,'time',lambda:2000)
    n=node('primary');n['spec']['unschedulable']=True;n['metadata']['annotations']={policy.OWNER:n['metadata']['uid']}
    data={'node':n,'pods':[],'workloads':[],'volumeattachments':[]}
    monkeypatch.setattr(lifecycle.observer,'get',lambda resource,**kw:data[resource])
    idle={'uid':'primary-uid','node':'primary','phase':'retirement-eligible','idleSeconds':1800,'idleSince':100,'lastObserved':1999,'blockers':[]}
    lifecycle.write(obs/'idle.json',{'primary':idle});lifecycle.write(slot/'desired.json',{'target':1})
    return data,idle,slot,obs


def gate():return lifecycle.RetirementGate('primary','primary-uid')


@pytest.mark.parametrize('change', ['young','stale','replacement','busy','attachment','demand','maintenance','foreign-cordon'])
def test_precommit_guards(env,change):
    data,idle,slot,obs=env
    if change=='young':idle['idleSince']=1000
    if change=='stale':idle['lastObserved']=1900
    if change=='replacement':idle['uid']='old'
    if change=='busy':data['pods']=[pod()]
    if change=='attachment':data['volumeattachments']=[{'spec':{'nodeName':'primary'}}]
    if change=='demand':data['workloads']=[{'metadata':{'name':'new'},'spec':{}}]
    if change=='maintenance':(slot/'maintenance').touch()
    if change=='foreign-cordon':data['node']['metadata']['annotations']={}
    lifecycle.write(obs/'idle.json',{'primary':idle})
    with pytest.raises(lifecycle.Cancelled):gate().prepare()
    assert not lifecycle.journal_path().exists()


def test_demand_after_prepare_cancels_before_commit(env,monkeypatch):
    data,*_=env;g=gate();g.prepare()
    data['workloads']=[{'metadata':{'name':'new'},'spec':{}}]
    reopened=[];monkeypatch.setattr(lifecycle.observer,'cordon',lambda n,on:reopened.append(on))
    with pytest.raises(lifecycle.Cancelled) as error:g.commit()
    g.fail(error.value)
    assert reopened==[False]
    assert lifecycle.read(lifecycle.journal_path())['phase']=='canceled'


def test_postcommit_demand_latches_across_later_empty_queue(env):
    data,_,slot,_=env;g=gate();g.prepare();g.commit()
    data['workloads']=[{'metadata':{'name':'new'},'spec':{}}];g.poll()
    assert lifecycle.read(lifecycle.journal_path())['rewakeQueued']
    data['workloads']=[];lifecycle.write(slot/'desired.json',{'target':0});g.finish()
    assert lifecycle.read(slot/'desired.json')['target']==1
    assert lifecycle.read(lifecycle.journal_path())['phase']=='wake-requested'


def test_ambiguous_shutdown_never_reopens_or_retries(env,monkeypatch):
    g=gate();g.prepare();g.commit()
    monkeypatch.setattr(lifecycle.observer,'cordon',lambda *_:pytest.fail('Must not reopen after commit'))
    g.fail(TimeoutError('unknown result'))
    with pytest.raises(RuntimeError,match='operator review'):gate()
    lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['phase']=='blocked'


def test_restart_during_commit_blocks_recovery(env):
    g=gate();g.prepare();g.commit();lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['error']=='interrupted-operation'


def test_ready_target_after_retirement_creates_once(env,monkeypatch):
    lifecycle.write(lifecycle.journal_path(),{'phase':'wake-requested'})
    calls=[];monkeypatch.setattr(lifecycle.runtime,'reconcile',lambda:calls.append('create'))
    # No retirement should be triggered after successful creation in this test.
    lifecycle.write(env[3]/'idle.json',{})
    lifecycle.tick();lifecycle.tick()
    assert calls==['create']
    assert lifecycle.read(lifecycle.journal_path())['phase']=='ready'


def test_creation_error_stops_automatic_retry(env,monkeypatch):
    lifecycle.write(lifecycle.journal_path(),{'phase':'retired'})
    def fail():raise RuntimeError('creation failed')
    monkeypatch.setattr(lifecycle.runtime,'reconcile',fail)
    with pytest.raises(RuntimeError):lifecycle.tick()
    lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['phase']=='blocked'


def test_secondary_cannot_use_automatic_path(env,monkeypatch):
    monkeypatch.setattr(lifecycle.runtime,'SLOT','secondary')
    with pytest.raises(RuntimeError,match='primary-prototype only'):gate()
    with pytest.raises(RuntimeError,match='primary-prototype only'):lifecycle.tick()



@pytest.mark.parametrize('arrival',['during-drain','after-shutdown','none'])
def test_runtime_retirement_integrates_cancel_and_rewake(env,monkeypatch,arrival):
    import retire
    data,_,slot,_=env
    data['node']['status'].update(addresses=[{'type':'InternalIP','address':'10.0.0.11'}],nodeInfo={'systemUUID':'vm-generation'})
    monkeypatch.setattr(retire,'STATE',slot)
    monkeypatch.setattr(retire,'PROVIDER',policy.IDENTITIES['primary'])
    monkeypatch.setattr(retire,'record',lambda *a,**kw:None)
    monkeypatch.setattr(lifecycle.observer,'cordon',lambda *a:None)
    calls=[];stopped=False
    def run(args,**kwargs):
        nonlocal stopped
        calls.append(args)
        if 'view' in args:return json.dumps({'clusters':[{'name':'laptop-wifi-PROTOTYPE','cluster':{'server':'https://10.0.2.15:6443'}}]})
        if args[-1]=='inspect':return json.dumps({'exists':True,'uuid':'vm-generation','ip':'10.0.0.11','status':'stopped' if stopped else 'running'})
        if 'get' in args and 'node' in args:return json.dumps(data['node'])
        if 'volumeattachments' in args:return '{"items":[]}'
        if 'drain' in args and arrival=='during-drain':data['workloads']=[{'metadata':{'name':'new'},'spec':{}}]
        if 'shutdown' in args:
            assert lifecycle.read(lifecycle.journal_path())['phase']=='shutdown-committed'
            stopped=True
            if arrival=='after-shutdown':data['workloads']=[{'metadata':{'name':'new'},'spec':{}}]
        if args[-1]=='retire vm-generation':return '{"retired_uuid":"vm-generation","status":"absent"}'
        return ''
    monkeypatch.setattr(retire,'run',run)
    if arrival=='during-drain':
        with pytest.raises(lifecycle.Cancelled):retire.retire('primary','primary-uid',idle=True)
        assert not any('shutdown' in call for call in calls)
        assert lifecycle.read(slot/'desired.json')['target']==1
    else:
        retire.retire('primary','primary-uid',idle=True)
        assert any('shutdown' in call for call in calls)
        assert lifecycle.read(slot/'desired.json')['target']==(1 if arrival=='after-shutdown' else 0)


def test_script_entry_uses_same_module_as_retirement_callback(monkeypatch):
    import runpy
    calls=[]
    monkeypatch.setattr(lifecycle,'main',lambda:calls.append('canonical'))
    runpy.run_path(lifecycle.__file__,run_name='__main__')
    assert calls==['canonical']


def test_mismatched_window_cannot_retire(env):
    _,idle,_,obs=env
    idle['idleSeconds']=300
    lifecycle.write(obs/'idle.json',{'primary':idle})
    with pytest.raises(lifecycle.Cancelled,match='idle-window-not-proven'):gate().prepare()


def test_no_recreation_until_demand_sets_target(env,monkeypatch):
    lifecycle.write(lifecycle.journal_path(),{'phase':'retired'})
    lifecycle.write(env[2]/'desired.json',{'target':0})
    monkeypatch.setattr(lifecycle.runtime,'reconcile',lambda:pytest.fail('No demand'))
    lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['phase']=='retired'


def test_maintenance_holds_queued_recreation(env,monkeypatch):
    lifecycle.write(lifecycle.journal_path(),{'phase':'wake-requested','rewakeQueued':True})
    (env[2]/'maintenance').touch()
    monkeypatch.setattr(lifecycle.runtime,'reconcile',lambda:pytest.fail('Maintenance hold'))
    lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['rewakeQueued']


def test_interrupted_creation_requires_review(env,monkeypatch):
    lifecycle.write(lifecycle.journal_path(),{'phase':'creating'})
    monkeypatch.setattr(lifecycle.runtime,'reconcile',lambda:pytest.fail('Cannot retry uncertain creation'))
    lifecycle.tick()
    assert lifecycle.read(lifecycle.journal_path())['error']=='interrupted-creation'
