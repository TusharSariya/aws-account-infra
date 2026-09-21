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
