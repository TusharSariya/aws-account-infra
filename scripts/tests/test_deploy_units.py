"""Affected acceptance selection and fail-closed release gates."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('units', Path(__file__).resolve().parents[1] / 'deploy-units.py')
units = importlib.util.module_from_spec(spec)
spec.loader.exec_module(units)


class SelectionTests(unittest.TestCase):
    def test_ci_plumbing_does_not_select_every_state(self):
        for path in ['.github/workflows/tofu-plan.yml', '.github/workflows/tofu-apply.yml',
                     'scripts/deploy-units.py', 'scripts/infra.sh', 'deploy-units.json']:
            self.assertEqual(units.select_units([path], units.load_units()), [], path)

    def test_every_workflow_and_runner_setup_select_no_infrastructure(self):
        root = Path(__file__).resolve().parents[2]
        paths = [str(p.relative_to(root)) for p in (root / '.github/workflows').glob('*.yml')]
        paths.extend(['.github/actions/talos-runner-setup/action.yml',
                      '.github/actions/setup-opentofu/action.yml'])
        for path in paths:
            self.assertEqual(units.select_units([path], units.load_units()), [], path)

    def test_workflow_routing_and_stages_use_selected_ids_not_dependency_metadata(self):
        selected = units.select_units(['config/environments/kubernetes/homelab/ai-values.yaml'],
                                      units.load_units())
        self.assertEqual([u['id'] for u in selected], ['kubernetes-homelab'])
        self.assertIn('talos-homelab', selected[0]['dependencies'])
        # A serialized-object substring check also matches dependency/watch fields.
        # Every workflow membership check must project only actual selected IDs.
        root = Path(__file__).resolve().parents[2]
        for name in ('tofu-plan.yml', 'tofu-apply.yml'):
            workflow = (root / '.github/workflows' / name).read_text()
            self.assertNotIn('contains(needs.detect.outputs.units,', workflow, name)
            for unit in ('proxmox-homelab', 'talos-homelab', 'kubernetes-homelab'):
                self.assertIn("contains(fromJSON(needs.detect.outputs.units).*.id, '" + unit + "')",
                              workflow, name)

    def test_shared_module_selects_only_consumers(self):
        selected = units.select_units(['modules/aws/ecr_repository/main.tf'], units.load_units())
        self.assertEqual({u['id'] for u in selected}, {'aws-staging-rag', 'aws-staging-court-booker'})
        selected = units.select_units(['modules/aws/encrypted_s3_bucket/main.tf'], units.load_units())
        self.assertEqual({u['id'] for u in selected}, {'aws-staging-rag', 'aws-staging-homelab-recovery'})

    def test_root_change_does_not_select_unchanged_prerequisites(self):
        selected = units.select_units(['config/environments/aws/staging/court-booker-api.tfvars'],
                                      units.ordered(units.load_units()))
        self.assertEqual([u['id'] for u in selected], ['aws-staging-court-booker-api'])

    def test_migration_helper_alone_selects_guarded_kubernetes_deployment(self):
        files = ['apps/platform/migration/reset.py']
        selected = units.select_units(files, units.load_units())
        self.assertEqual([unit['cloud'] for unit in selected], ['kubernetes'])
        self.assertEqual(units.acceptance_suite(files, selected), 'all')
        self.assertTrue(units.storage_checks_required(files, selected))

    def test_test_only_changes_do_not_require_apply_but_select_acceptance(self):
        for path, suite in [('scripts/homelab-cilium-validate.sh', 'network'),
                            ('scripts/homelab-storage-validate.py', 'pvc')]:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertEqual(selected, [])
                self.assertEqual(units.acceptance_suite([path], selected), suite)

    def test_shared_helpers_and_workflows_select_both_suites(self):
        for path in ['scripts/homelab-readiness.sh', 'scripts/talos-ci.py',
                     '.github/actions/talos-check/action.yml',
                     '.github/workflows/homelab-acceptance.yml', 'live/proxmox/homelab/main.tf']:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertEqual(units.acceptance_suite([path], selected), 'all')

    def test_unrelated_docs_and_aws_changes_do_not_run_cluster_tests(self):
        for path in ['docs/plans/homelab-recovery.md', 'apps/lambda/python/3.14/court-booker/app.py']:
            selected = units.select_units([path], units.load_units())
            self.assertEqual(units.acceptance_suite([path], selected), 'none')


class ApplicationSelectionTests(unittest.TestCase):
    def test_application_edit_selects_only_application_root(self):
        for path in ['live/kubernetes/homelab/main.tf', 'config/environments/kubernetes/homelab/pihole-values.yaml', '.github/actions/kubernetes-deploy/action.yml']:
            self.assertEqual([u['id'] for u in units.select_units([path], units.ordered(units.load_units()))], ['kubernetes-homelab'])

    def test_lifecycle_and_image_inputs_select_required_application_acceptance(self):
        for path in ['apps/platform/lifecycle/runtime.py', 'apps/containers/ollama/lifecycle/gateway.go',
                     'apps/containers/odysseus/lifecycle/tracking.py', 'scripts/ollama-image-context.py',
                     'scripts/tests/test_lifecycle_state.py',
                     'scripts/odysseus-scheduler-acceptance.py']:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertEqual([unit['id'] for unit in selected], ['kubernetes-homelab'])
                self.assertEqual(units.acceptance_suite([path], selected), 'all')
                self.assertTrue(units.storage_checks_required([path], selected))

    def test_order_places_applications_after_foundation(self):
        ordered = [u['id'] for u in units.ordered(units.load_units())]
        self.assertLess(ordered.index('talos-homelab'), ordered.index('kubernetes-homelab'))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.needs = {'detect': {'result': 'success', 'outputs': {
            'units': '[{"id":"talos-homelab"}]', 'suite': 'all'}},
            'apply': {'result': 'success', 'outputs': {'needs_worker_reboot': 'false'}},
            'acceptance': {'result': 'success'}, 'worker-maintenance': {'result': 'skipped'}}

    def test_application_apply_cannot_be_skipped(self):
        self.needs['detect']['outputs'] = {'units': '[{"id":"kubernetes-homelab"}]', 'suite': 'none'}
        self.needs['apply']['result'] = 'skipped'
        with self.assertRaises(ValueError):
            units.acceptance_gate(self.needs, True, False)

    def test_requested_lifecycle_maintenance_cannot_skip_fail_or_cancel(self):
        for result in ('skipped', 'failure', 'cancelled'):
            self.needs['lifecycle-maintenance'] = {'result': result}
            with self.subTest(result=result), self.assertRaises(ValueError):
                units.acceptance_gate(self.needs, True, False, True)
        self.needs['lifecycle-maintenance']['result'] = 'success'
        units.acceptance_gate(self.needs, True, False, True)

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


class StorageSelectionTests(unittest.TestCase):
    def test_credential_recipes_select_deployment_and_full_checks(self):
        for path in ('scripts/issue-capacity-credentials.py', 'scripts/enroll-capacity-host-key.sh',
                     'scripts/quota-acceptance.py'):
            selected = units.select_units([path], units.load_units())
            self.assertEqual([unit['cloud'] for unit in selected], ['kubernetes'])
            self.assertEqual(units.acceptance_suite([path], selected), 'all')
            self.assertTrue(units.storage_checks_required([path], selected))

    def test_storage_inputs_and_tests_select_required_gate(self):
        for path in ['apps/platform/storage/collector.py', 'charts/homelab-capacity/values.yaml',
                     'scripts/tests/test_capacity.py', 'scripts/tests/storage/quota-linux.sh',
                     'scripts/install-homelab-capacity.sh', '.github/workflows/storage-foundation.yml']:
            with self.subTest(path=path):
                selected = units.select_units([path], units.load_units())
                self.assertTrue(units.storage_checks_required([path], selected))

    def test_storage_gate_rejects_skips_cancellations_and_failures(self):
        for result in ['skipped', 'cancelled', 'failure']:
            needs = {'detect': {'result': 'success', 'outputs': {'units': '[]', 'suite': 'none', 'storage': 'true'}},
                     'storage-foundation': {'result': result}}
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, 'storage checks'):
                units.acceptance_gate(needs, False, False)

    def test_storage_gate_rejects_missing_job(self):
        with self.assertRaisesRegex(ValueError, 'storage checks'):
            units.acceptance_gate({'detect': {'result': 'success', 'outputs': {
                'units': '[]', 'suite': 'none', 'storage': 'true'}}}, False, False)


if __name__ == '__main__':
    unittest.main()
