import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('slot_reconcile',Path(__file__).parents[1]/'reconcile.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
READY={'status':{'conditions':[{'type':'Ready','status':'True'}]}}
DRIVER={'name':'csi.proxmox.sinextra.dev'}

def test_empty_daemonset_result_is_not_ready():
    assert not m.storage_ready([], [DRIVER])

def test_registered_driver_without_ready_pod_is_not_ready():
    assert not m.storage_ready([{}], [DRIVER])

def test_ready_pod_without_registered_driver_is_not_ready():
    assert not m.storage_ready([READY], [])

def test_worker_eligible_only_after_both_conditions():
    assert m.storage_ready([READY], [DRIVER])


def test_talos_api_waits_through_connection_refusal(monkeypatch):
    import subprocess
    import reconcile
    calls=[]
    def run(args, timeout):
        calls.append(args)
        if len(calls)==1:raise subprocess.CalledProcessError(1,args)
        return 'Server v1.13.9'
    monkeypatch.setattr(reconcile,'run',run)
    monkeypatch.setattr(reconcile.time,'sleep',lambda _:None)
    reconcile.wait_talos('10.0.0.9')
    assert len(calls)==2 and all('version' in a and 'apply-config' not in a for a in calls)


def test_talos_api_wait_is_bounded(monkeypatch):
    import subprocess
    import pytest
    import reconcile
    clock=iter([0,0,181])
    monkeypatch.setattr(reconcile.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(reconcile.time,'sleep',lambda _:None)
    def run(args, timeout):raise subprocess.TimeoutExpired(args,timeout)
    monkeypatch.setattr(reconcile,'run',run)
    with pytest.raises(TimeoutError,match='readiness deadline'):reconcile.wait_talos('10.0.0.9')
