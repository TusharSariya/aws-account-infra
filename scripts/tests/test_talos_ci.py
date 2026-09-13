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
        for field, value in [('kubeProxyReplacement', True), ('routingMode', 'native')]:
            with self.subTest(field=field):
                wrong = dict(values, **{field: value})
                cilium['change']['after']['values'] = [ci.yaml.safe_dump(wrong)]
                with self.assertRaisesRegex(ValueError, 'retain kube-proxy'):
                    ci.guard_plan(self.plan)
        cilium['change']['actions'] = ['delete', 'create']
        with self.assertRaisesRegex(ValueError, 'destructive'):
            ci.guard_plan(self.plan)

    def test_missing_bootstrap_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing bootstrap'):
            ci.guard_plan({'resource_changes': [self.cp]})


if __name__ == '__main__':
    unittest.main()
