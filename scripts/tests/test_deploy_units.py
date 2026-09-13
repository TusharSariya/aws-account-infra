"""Affected acceptance selection and fail-closed release gates."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('units', Path(__file__).resolve().parents[1] / 'deploy-units.py')
units = importlib.util.module_from_spec(spec)
spec.loader.exec_module(units)


class SelectionTests(unittest.TestCase):
    def test_test_only_changes_do_not_require_apply_but_select_acceptance(self):
        for path, suite in [('scripts/homelab-cilium-validate.sh', 'network'),
                            ('scripts/homelab-storage-validate.py', 'pvc')]:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertEqual(selected, [])
                self.assertEqual(units.acceptance_suite([path], selected), suite)

    def test_shared_helpers_and_workflows_select_both_suites(self):
        for path in ['scripts/homelab-readiness.sh', 'scripts/talos-ci.py',
                     '.github/actions/talos-check/action.yml', '.github/workflows/tofu-apply.yml',
                     '.github/workflows/homelab-acceptance.yml', 'live/proxmox/homelab/main.tf']:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertEqual(units.acceptance_suite([path], selected), 'all')

    def test_unrelated_docs_and_aws_changes_do_not_run_cluster_tests(self):
        for path in ['docs/plans/homelab-recovery.md', 'apps/lambda/python/3.14/court-booker/app.py']:
            selected = units.select_units([path], units.load_units())
            self.assertEqual(units.acceptance_suite([path], selected), 'none')


class GateTests(unittest.TestCase):
    def setUp(self):
        self.needs = {'detect': {'result': 'success', 'outputs': {
            'units': '[{"id":"talos-homelab"}]', 'suite': 'all'}},
            'apply': {'result': 'success', 'outputs': {'needs_worker_reboot': 'false'}},
            'acceptance': {'result': 'success'}, 'worker-maintenance': {'result': 'skipped'}}

    def test_successful_apply_and_acceptance_pass(self):
        units.acceptance_gate(self.needs, True, False)

    def test_infrastructure_pr_without_apply_label_cannot_merge(self):
        self.needs['apply']['result'] = 'skipped'
        with self.assertRaisesRegex(ValueError, 'require the apply label'):
            units.acceptance_gate(self.needs, False, False)

    def test_failed_cancelled_or_skipped_acceptance_blocks_release(self):
        for state in ['failure', 'cancelled', 'skipped']:
            needs = copy.deepcopy(self.needs)
            needs['acceptance']['result'] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                units.acceptance_gate(needs, True, False)

    def test_failed_requested_apply_cannot_hide_behind_skipped_jobs(self):
        for state in ['failure', 'cancelled', 'skipped']:
            needs = copy.deepcopy(self.needs)
            needs['apply']['result'] = state
            needs['acceptance']['result'] = 'skipped'
            with self.subTest(state=state), self.assertRaises(ValueError):
                units.acceptance_gate(needs, True, False)

    def test_test_only_pr_requires_acceptance_even_with_no_units(self):
        self.needs['detect']['outputs']['units'] = '[]'
        self.needs['apply']['result'] = 'skipped'
        units.acceptance_gate(self.needs, False, False)
        self.needs['acceptance']['result'] = 'skipped'
        with self.assertRaises(ValueError):
            units.acceptance_gate(self.needs, False, False)

    def test_unrelated_change_can_skip_apply_and_acceptance(self):
        self.needs['detect']['outputs'] = {'units': '[]', 'suite': 'none'}
        self.needs['apply']['result'] = 'skipped'
        self.needs['acceptance']['result'] = 'skipped'
        units.acceptance_gate(self.needs, False, False)

    def test_first_provision_and_requested_reboot_require_success(self):
        for first, requested in [('true', False), ('false', True)]:
            self.needs['apply']['outputs']['needs_worker_reboot'] = first
            self.needs['worker-maintenance']['result'] = 'skipped'
            with self.assertRaises(ValueError):
                units.acceptance_gate(self.needs, True, requested)
            self.needs['worker-maintenance']['result'] = 'success'
            units.acceptance_gate(self.needs, True, requested)


if __name__ == '__main__':
    unittest.main()
