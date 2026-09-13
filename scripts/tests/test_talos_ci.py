"""Exercise plan guards at the parsed OpenTofu plan boundary."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('talos_ci', Path(__file__).resolve().parents[1] / 'talos-ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def resource(address, actions, **after):
    return {'address': address, 'change': {'actions': actions, 'after': after}}


class PlanGuardTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = resource('talos_machine_bootstrap.cluster', ['update'])
        self.bootstrap['change']['importing'] = {'id': 'homelab-existing-20260913'}
        self.cp = resource('talos_machine_configuration_apply.control_plane', ['create'], apply_mode='no_reboot')
        self.plan = {'resource_changes': [self.bootstrap, self.cp]}

    def test_existing_bootstrap_import_and_configuration_adoption(self):
        result = ci.guard_plan(self.plan)
        self.assertTrue(result[0]['import'])
        self.assertEqual(result[1]['actions'], ['create'])

    def test_bootstrap_creation_is_rejected(self):
        self.bootstrap['change']['actions'] = ['create']
        with self.assertRaisesRegex(ValueError, 'never created'):
            ci.guard_plan(self.plan)

    def test_vm_or_reset_or_replacement_is_rejected(self):
        for change in [resource('proxmox_virtual_environment_vm.guest', ['create']),
                       resource('talos_machine_configuration_apply.worker[0]', ['delete', 'create']),
                       resource('talos_machine_configuration_apply.worker[0]', ['update'], on_destroy={'reset': True})]:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    ci.guard_plan({'resource_changes': [self.bootstrap, change]})

    def test_control_plane_reboot_is_rejected(self):
        self.cp['change']['after']['apply_mode'] = 'auto'
        with self.assertRaisesRegex(ValueError, 'must not reboot'):
            ci.guard_plan(self.plan)

    def test_state_rejects_credentials_and_rendered_config(self):
        ci.assert_public_state({'resources': [{'attributes': {'machine_configuration': None}}]})
        for key in ['client_key', 'machine_configuration', 'machine_configuration_input_wo']:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, 'persisted'):
                    ci.assert_public_state({'resources': [{'attributes': {key: 'test-only-value'}}]})

    def test_cilium_plan_preserves_network_contract(self):
        values = {'kubeProxyReplacement': False, 'routingMode': 'tunnel',
                  'tunnelProtocol': 'vxlan', 'ipam': {'mode': 'kubernetes'}}
        cilium = resource('helm_release.cilium', ['create'], name='cilium', namespace='kube-system',
                          version='1.20.1', chart='./.terraform/cilium-1.20.1.tgz',
                          values=[ci.yaml.safe_dump(values)])
        self.plan['resource_changes'].append(cilium)
        self.assertEqual(ci.guard_plan(self.plan)[-1]['actions'], ['create'])
        cilium['change']['actions'] = ['delete', 'create']
        with self.assertRaisesRegex(ValueError, 'destructive'):
            ci.guard_plan(self.plan)

    def test_local_path_requires_worker_data_disk(self):
        values = ci.yaml.safe_load((ci.INPUTS / 'local-path-values.yaml').read_text())
        release = resource('helm_release.local_path', ['create'], name='local-path-provisioner',
                           namespace='local-path-storage', version='0.0.37',
                           chart='./.terraform/local-path-provisioner', values=[ci.yaml.safe_dump(values)])
        self.plan['resource_changes'].append(release)
        ci.guard_plan(self.plan)
        values['nodePathMap'][0]['paths'] = ['/var/lib/local-path']
        release['change']['after']['values'] = [ci.yaml.safe_dump(values)]
        with self.assertRaisesRegex(ValueError, 'worker data mount'):
            ci.guard_plan(self.plan)

    def test_storage_release_deletion_or_retargeting_is_rejected(self):
        policy = resource('helm_release.storage_policy', ['create'], name='homelab-storage-policy',
                          namespace='kube-system', version='0.1.0', chart='./charts/storage-policy')
        self.plan['resource_changes'].append(policy)
        ci.guard_plan(self.plan)
        policy['change']['actions'] = ['delete']
        with self.assertRaises(ValueError):
            ci.guard_plan(self.plan)
        policy['change']['actions'] = ['update']
        policy['change']['after']['namespace'] = 'default'
        with self.assertRaises(ValueError):
            ci.guard_plan(self.plan)

    def test_missing_bootstrap_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing bootstrap'):
            ci.guard_plan({'resource_changes': [self.cp]})


class StorageGuardTests(unittest.TestCase):
    def setUp(self):
        self.disks = [
            {'metadata': {'id': 'sda'}, 'spec': {'size': 100 * 1024**3}},
            {'metadata': {'id': 'sdb'}, 'spec': {'size': 1200 * 1024**3,
             'dev_path': '/dev/sdb', 'readonly': False, 'cdrom': False, 'symlinks': [ci.DATA_ID]}}]
        self.volumes = [{'spec': {'dev_path': '/dev/sdb', 'type': 'disk', 'name': ''}}]

    def test_blank_verified_data_disk_is_allowed(self):
        self.assertEqual(ci.guard_storage_disks(self.disks, self.volumes), 'blank')

    def test_os_disk_wrong_size_or_device_identity_rejected(self):
        for field, value in [('size', 100 * 1024**3), ('dev_path', '/dev/sda'),
                             ('symlinks', []), ('readonly', True)]:
            with self.subTest(field=field):
                import copy
                disks = copy.deepcopy(self.disks)
                disks[1]['spec'][field] = value
                with self.assertRaises(ValueError):
                    ci.guard_storage_disks(disks, self.volumes)

    def test_existing_unknown_filesystem_or_partition_rejected(self):
        self.volumes[0]['spec']['name'] = 'ext4'
        with self.assertRaisesRegex(ValueError, 'unexpected existing content'):
            ci.guard_storage_disks(self.disks, self.volumes)

    def test_existing_expected_partition_is_reused_but_wrong_label_location_rejected(self):
        self.volumes[0]['spec']['name'] = 'gpt'
        partition = {'spec': {'dev_path': '/dev/sdb1', 'parent_dev_path': '/dev/sdb',
                             'type': 'partition', 'partition_label': ci.VOLUME,
                             'name': 'xfs', 'size': 1199 * 1024**3}}
        self.volumes.append(partition)
        self.assertEqual(ci.guard_storage_disks(self.disks, self.volumes), 'existing')
        partition['spec']['dev_path'] = '/dev/sda4'
        with self.assertRaises(ValueError):
            ci.guard_storage_disks(self.disks, self.volumes)

    def test_checked_in_config_and_unsafe_selector(self):
        config = (ci.ROOT / 'config/environments/proxmox/homelab/talos/patches/talos-worker-01.yaml').read_text()
        ci.guard_storage_config({'talos-worker-01': config, 'talos-cp-01': 'machine: {}'})
        with self.assertRaises(ValueError):
            ci.guard_storage_config({'talos-worker-01': config.replace(ci.SELECTOR, '!system_disk')})

    def test_mount_must_be_actual_data_filesystem(self):
        volume = [{'metadata': {'id': ci.VOLUME}, 'spec': {'phase': 'ready', 'location': '/dev/sdb1'}}]
        mount = [{'metadata': {'id': ci.VOLUME}, 'spec': {'source': '/dev/sdb1', 'target': ci.MOUNT, 'filesystem': 'xfs'}}]
        self.assertTrue(ci.check_storage_mount(volume, mount))
        mount[0]['spec']['source'] = '/dev/sda4'
        self.assertFalse(ci.check_storage_mount(volume, mount))


if __name__ == '__main__':
    unittest.main()
