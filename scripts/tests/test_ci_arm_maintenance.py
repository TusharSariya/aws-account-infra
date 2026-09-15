"""Saved maintenance must reject changed retained storage before mutation."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('arm_maintenance', Path(__file__).resolve().parents[1]/'homelab-ci-arm-maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class StorageIdentityTests(unittest.TestCase):
    def setUp(self):
        self.vm = {'scsi1': 'local-lvm:vm-102-disk-2,size=1200G'}
        self.volumes = [{'uid': 'retained-pv', 'spec': {'local': {'path': '/data/original'}}}]
        self.identities = {'/dev/sdb1': ['filesystem-uuid', 'partition-uuid']}
        self.receipt = copy.deepcopy({'data_disk': self.vm['scsi1'], 'persistent_volumes': self.volumes, 'partition_identities': self.identities})

    def test_unchanged_storage_is_accepted(self):
        maintenance.guard_storage_identity(self.receipt, self.vm, self.volumes, self.identities)

    def test_same_size_replacement_disk_is_rejected(self):
        self.vm['scsi1'] = 'local-lvm:replacement,size=1200G'
        with self.assertRaisesRegex(ValueError, 'saved maintenance plan'):
            maintenance.guard_storage_identity(self.receipt, self.vm, self.volumes, self.identities)

    def test_replaced_pv_is_rejected(self):
        self.volumes[0]['uid'] = 'replacement-pv'
        with self.assertRaisesRegex(ValueError, 'saved maintenance plan'):
            maintenance.guard_storage_identity(self.receipt, self.vm, self.volumes, self.identities)

    def test_reformatted_partition_is_rejected(self):
        self.identities['/dev/sdb1'][0] = 'replacement-filesystem'
        with self.assertRaisesRegex(ValueError, 'saved maintenance plan'):
            maintenance.guard_storage_identity(self.receipt, self.vm, self.volumes, self.identities)
