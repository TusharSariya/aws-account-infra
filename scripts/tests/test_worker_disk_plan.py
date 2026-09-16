import copy
import unittest
from worker_disk_plan import guard, WORKER

class DiskGuardTests(unittest.TestCase):
    def plan(self):
        before = dict(vm_id=102, name='talos-worker-01', node_name='pve', reboot_after_update=False,
            disk=[dict(interface=i, size=s, datastore_id='local-lvm', path_in_datastore=p)
                  for i,s,p in [('scsi0',100,'vm-102-disk-1'),('scsi1',1200,'vm-102-disk-2')]])
        after = copy.deepcopy(before); after['disk'][0]['size'] = 128
        return {'resource_changes':[dict(address=WORKER,change=dict(actions=['update'],before=before,after=after))]}
    def test_exact_growth_only(self):
        self.assertEqual(guard(self.plan()),[WORKER])
        for key,value in [('started',False),('name','other'),('vm_id',100)]:
            plan=self.plan();plan['resource_changes'][0]['change']['after'][key]=value
            with self.assertRaises(ValueError):guard(plan)
        for size in [64,100,129]:
            plan=self.plan();plan['resource_changes'][0]['change']['after']['disk'][0]['size']=size
            with self.assertRaises(ValueError):guard(plan)
    def test_replacements_unknown_and_other_disks_rejected(self):
        for key,value in [('actions',['delete','create']),('after_unknown',{'disk':True})]:
            plan=self.plan();plan['resource_changes'][0]['change'][key]=value
            with self.assertRaises(ValueError):guard(plan)
        plan=self.plan();plan['resource_changes'][0]['change']['after']['disk'][1]['size']=1300
        with self.assertRaises(ValueError):guard(plan)
        with self.assertRaises(ValueError):guard({'resource_changes':[]})
