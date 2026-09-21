import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('pve_slot', ROOT/'pve-slot.py')
pve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pve)
from retire import owned_node, PROVIDER

UUID = '01234567-89ab-cdef-0123-456789abcdef'

def config():
    return {'name': pve.NAME, 'description': 'Owner one-slot-proof. Disposable prototype only. Never production.',
            'smbios1': 'uuid='+UUID, 'onboot': 0, 'scsi0': 'local-lvm:vm-9105-disk-0,size=24G', 'ide2': pve.ISO+',media=cdrom'}

def test_only_disposable_os_is_accepted():
    pve.disposable_config(config(), UUID)

@pytest.mark.parametrize('key', ['scsi1', 'unused0', 'virtio1', 'efidisk0', 'tpmstate0'])
def test_any_extra_disk_blocks_deletion(key):
    cfg=config();cfg[key]='local-lvm:vm-9199-pvc-retained'
    with pytest.raises(RuntimeError):pve.disposable_config(cfg, UUID)

@pytest.mark.parametrize('field,value', [('name','production'), ('smbios1','uuid=changed'), ('description','changed'), ('onboot',1), ('lock','backup'), ('template',1), ('scsi0','local-lvm:vm-103-disk-0')])
def test_identity_or_ownership_change_blocks_deletion(field,value):
    cfg=config();cfg[field]=value
    with pytest.raises(RuntimeError):pve.disposable_config(cfg, UUID)

def test_running_vm_never_reaches_destroy(monkeypatch):
    import json
    calls=[]
    def run(*args):
        calls.append(args)
        return json.dumps(config() if args[2].endswith('/config') else {'status':'running'})
    monkeypatch.setattr(pve,'run',run)
    with pytest.raises(RuntimeError):pve.retire(UUID)
    assert not any(c[0]=='qm' for c in calls)

@pytest.mark.parametrize('change', ['uid','provider','control-plane'])
def test_replaced_or_foreign_node_is_refused(change):
    node={'metadata':{'name':'test','uid':'original','labels':{}},'spec':{'providerID':PROVIDER}}
    if change=='uid':node['metadata']['uid']='new'
    elif change=='provider':node['spec']['providerID']='proxmox://primary/102'
    else:node['metadata']['labels']['node-role.kubernetes.io/control-plane']=''
    with pytest.raises(RuntimeError):owned_node(node,'test','original')

def test_replacement_restores_scoped_user_and_token_access(monkeypatch):
    calls=[]
    monkeypatch.setattr(pve,'run',lambda *args: calls.append(args))
    pve.ensure_csi_access()
    assert calls == [
        ('pveum','acl','modify','/vms/9105','--roles','Prototype105Disk','--users','prototype105-csi@pve'),
        ('pveum','acl','modify','/vms/9105','--roles','Prototype105Disk','--tokens','prototype105-csi@pve!csi')]

def test_same_ip_with_new_vm_generation_never_drains(monkeypatch, tmp_path):
    import json
    import retire as runtime
    (tmp_path/'desired.json').write_text('{"target":1}')
    monkeypatch.setattr(runtime,'STATE',tmp_path)
    calls=[]
    node={'metadata':{'name':'old','uid':'old-uid','labels':{}},'spec':{'providerID':PROVIDER},
          'status':{'addresses':[{'type':'InternalIP','address':'10.0.0.9'}],
                    'nodeInfo':{'systemUUID':'old-hardware'}}}
    def run(args, **kwargs):
        calls.append(args)
        if 'view' in args:return json.dumps({'clusters':[{'name':'laptop-wifi-PROTOTYPE','cluster':{'server':'https://10.0.2.15:6443'}}]})
        if args[-1]=='inspect':return json.dumps({'exists':True,'uuid':UUID,'ip':'10.0.0.9'})
        if 'get' in args and 'node' in args:return json.dumps(node)
        raise AssertionError('Unexpected mutation')
    monkeypatch.setattr(runtime,'run',run)
    with pytest.raises(RuntimeError, match='hardware generation mismatch'):runtime.retire('old','old-uid')
    assert not any('drain' in c or 'shutdown' in c for c in calls)
