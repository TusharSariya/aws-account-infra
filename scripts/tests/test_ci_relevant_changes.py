import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "changes", Path(__file__).resolve().parents[1] / "ci-relevant-changes.py"
)
changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changes)


class RelevantChangesTests(unittest.TestCase):
    def test_documentation_skips_expensive_checks(self):
        for scope in changes.SCOPES:
            self.assertFalse(changes.relevant(scope, ["docs/homelab-kueue.md", "README.md"]))

    def test_root_and_nested_terraform(self):
        for scope in ["checkov", "tflint", "trivy"]:
            for path in ["main.tf", "live/aws/example/main.tf"]:
                self.assertTrue(changes.relevant(scope, [path]))

    def test_shell_inputs_select_shell_checks(self):
        for path in [
            "scripts/example.sh",
            "scripts/git-hooks/pre-push",
            "mocks/localstack/smoke.sh",
            "tests/display-mode.bats",
            ".shellcheckrc",
        ]:
            self.assertTrue(changes.relevant("config-shell", [path]))
            self.assertIn("config-shell", changes.selection([path])["checks"])
            self.assertIn("homelab-config-tests", changes.selection([path])["checks"])
        self.assertIn(
            "config-shell",
            changes.selection([".github/workflows/homelab-config-tests.yml"])["checks"],
        )

    def test_retired_micro_suites_have_no_scope(self):
        for name in ["shell", "runner-catalog", "kubernetes-validation", "main-platform-validation"]:
            self.assertNotIn(name, changes.SCOPES)
        checks = set(changes.selection(["scripts/runner_catalog.py"])["checks"])
        self.assertTrue({"config-runner-catalog", "homelab-config-tests"} <= checks)

    def test_deleted_shell_paths_still_select_shell_checks(self):
        # The production detector uses git diff --name-only --no-renames, so a
        # deleted path reaches the same matcher as an existing path.
        self.assertTrue(changes.relevant("config-shell", ["scripts/retired-script.sh"]))
        self.assertTrue(changes.relevant("config-shell", ["tests/retired-test.bats"]))

    def test_runtime_and_filter_changes_invalidate_checks(self):
        for scope in changes.SCOPES:
            for path in [".github/actions/talos-runner-setup/action.yml", "scripts/ci-relevant-changes.py"]:
                self.assertTrue(changes.relevant(scope, [path]))

    def test_shell_shared_ci_dependencies(self):
        for path in [
            ".github/actions/talos-runner-setup/action.yml",
            ".github/actions/nexus-dependency-cache/action.yml",
            "scripts/ci-relevant-changes.py",
        ]:
            self.assertTrue(changes.relevant("config-shell", [path]))

    def test_localstack_dependencies(self):
        self.assertTrue(changes.relevant("localstack", ["apps/ecr/court-booker/tests/test_api.py"]))
        self.assertFalse(changes.relevant("localstack", ["apps/containers/ollama/Dockerfile"]))


if __name__ == "__main__":
    unittest.main()


class FullDiffTests(unittest.TestCase):
    def test_applications_are_independent_and_manual_selects_all(self):
        self.assertEqual(changes.selection(['apps/lambda/python/3.14/iracing-calendar/uv.lock'])['applications'], ['iracing-calendar'])
        self.assertEqual(set(changes.selection(None)['applications']), set(changes.APPLICATIONS))
        self.assertEqual(changes.selection(['README.md'])['checks'], [])
        self.assertEqual(changes.selection(['README.md'])['units'], [])

    def test_suite_dependencies_always_select_executable_children(self):
        children = {name for name in changes.SCOPES if name.startswith('apps-')}
        for paths in [
            ['.github/workflows/tofu-plan.yml'],
            ['.github/workflows/homelab-ai-migration.yml'],
            ['.github/workflows/tofu-plan.yml', 'apps/platform/postgres/backup.py'],
        ]:
            with self.subTest(paths=paths):
                checks = set(changes.selection(paths)['checks'])
                self.assertIn('homelab-apps-tests', checks)
                self.assertTrue(children.issubset(checks))

    def test_suite_workflow_edit_selects_every_child(self):
        for suite, prefix in [('homelab-config-tests', 'config-'), ('homelab-apps-tests', 'apps-'),
                              ('offline-validation', 'validation-')]:
            with self.subTest(suite=suite):
                children = {name for name in changes.SCOPES if name.startswith(prefix)}
                checks = set(changes.selection([f'.github/workflows/{suite}.yml'])['checks'])
                self.assertIn(suite, checks)
                self.assertTrue(children <= checks, sorted(children - checks))
        config = {'config-workflow', 'config-shell', 'config-runner-catalog', 'config-proxmox', 'config-talos'}
        self.assertEqual({n for n in changes.SCOPES if n.startswith('config-')}, config)

    def test_offline_validation_children_select_independently(self):
        kubernetes = set(changes.selection(['validation/kubernetes/core.py'])['checks'])
        self.assertTrue({'offline-validation', 'validation-kubernetes'} <= kubernetes)
        self.assertNotIn('validation-main-platform', kubernetes)
        platform = set(changes.selection(['scripts/main_cluster_guard.py'])['checks'])
        self.assertTrue({'offline-validation', 'validation-main-platform'} <= platform)
        self.assertNotIn('validation-kubernetes', platform)
        for workflow in ['tofu-plan.yml', 'ci-validation.yml']:
            text = (changes.ROOT / '.github/workflows' / workflow).read_text()
            self.assertIn('uses: ./.github/workflows/offline-validation.yml', text)
            self.assertNotIn('kubernetes-validation', text)
            self.assertNotIn('main-platform-validation', text)

    def test_child_marker_check_fails_closed(self):
        spec = importlib.util.spec_from_file_location(
            'markers', changes.ROOT / 'scripts/ci-child-markers.py')
        markers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(markers)
        selected = ['homelab-config-tests', 'config-shell', 'config-talos', 'apps-postgres']
        self.assertEqual(markers.missing(selected, 'config-', ['config-shell']), ['config-talos'])
        self.assertEqual(markers.missing(selected, 'config-', ['config-shell', 'config-talos']), [])
        self.assertEqual(markers.missing(selected, 'apps-', [], exempt=['apps-postgres']), [])

    def test_ecr_images_follow_image_directories(self):
        names = sorted(p.parent.name for p in (changes.ROOT / 'apps/ecr').glob('*/Dockerfile'))
        self.assertIn('court-booker', names)
        self.assertEqual(changes.selection(['apps/ecr/court-booker/app.py'])['images'], ['court-booker'])
        self.assertEqual(changes.selection(['.github/workflows/ecr-push.yml'])['images'], names)
        self.assertEqual(changes.selection(None)['images'], names)
        self.assertEqual(changes.selection(['README.md'])['images'], [])
        # README.md sits directly in apps/ecr and a directory without a Dockerfile is never an image.
        self.assertEqual(changes.ecr_images(['apps/ecr/README.md', 'apps/ecr/no-dockerfile/x.py']), [])
        # CI plumbing changes select every check but never push images.
        self.assertEqual(changes.selection(['scripts/ci-relevant-changes.py'])['images'], [])

    def test_sdk_required_follows_specs_and_generators(self):
        for path in ['sdk/targets/python/x', 'scripts/sdk-generate.sh', 'specs/upace/openapi.yaml']:
            self.assertEqual(changes.selection([path])['sdk_required'], 'true', path)
        for path in ['specs/upace/README.md', 'README.md']:
            self.assertEqual(changes.selection([path])['sdk_required'], 'false', path)
        self.assertEqual(changes.selection(None)['sdk_required'], 'true')

    def test_workflows_use_the_shared_selector(self):
        for workflow in ['ecr-push.yml', 'sdk-publish-stable.yml']:
            text = (changes.ROOT / '.github/workflows' / workflow).read_text()
            self.assertIn('python3 scripts/ci-relevant-changes.py', text)
            self.assertNotIn('"git", "diff"', text)
        self.assertFalse((changes.ROOT / '.github/actions/relevant-changes').exists())

    def test_dependencies_and_module_consumers(self):
        result = changes.selection(['modules/aws/encrypted_s3_bucket/main.tf'])
        self.assertTrue(result['units'])
        self.assertIn('modules/aws/encrypted_s3_bucket', result['terraform_dirs'])
        self.assertTrue(any(p.startswith('live/aws/') for p in result['terraform_dirs']))
        self.assertIn('apps-postgres', changes.selection(['apps/platform/postgres/backup.py'])['checks'])
        self.assertNotIn('apps-documents', changes.selection(['apps/platform/postgres/backup.py'])['checks'])

    def test_real_git_diff_has_no_file_limit_and_includes_deleted_rename_source(self):
        import subprocess
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args): return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
            git('init','-q');git('config','user.name','Selection test');git('config','user.email','test@example.invalid')
            (root/'old.py').write_text('original');git('add','.');git('commit','-qm','base');base=git('rev-parse','HEAD')
            (root/'old.py').rename(root/'renamed.py')
            for i in range(1100):(root/f'doc-{i}.md').write_text('doc')
            git('add','.');git('commit','-qm','head');head=git('rev-parse','HEAD')
            with patch.object(changes,'ROOT',root):
                paths=changes.changed_paths({'before':base,'after':head},'push')
                self.assertEqual(len(paths),1102)
                self.assertIn('old.py',paths);self.assertIn('renamed.py',paths)
                self.assertEqual(set(paths),set(changes.changed_paths({'pull_request':{'base':{'sha':base},'head':{'sha':head}}},'pull_request')))
                with self.assertRaises(subprocess.CalledProcessError):changes.changed_paths({'before':'bad-revision','after':head},'push')

    def test_gate_rejects_failed_cancelled_and_skipped_selected_checks(self):
        import os
        from unittest.mock import patch
        # Exercise the actual required-gate program from the workflow, without
        # duplicating its implementation in the test.
        source=(changes.ROOT/'.github/workflows/tofu-plan.yml').read_text()
        gate=source.split('  plan-gate:',1)[1].split('  checkov:',1)[0]
        program=gate.split("python3 - <<'PYTHON'",1)[1].split('PYTHON',1)[0]
        import textwrap
        program=textwrap.dedent(program)
        for result in ['failure','cancelled','skipped']:
            needs={'detect':{'result':'success','outputs':{'checks':'["checkov"]'}},'checkov':{'result':result}}
            with patch.dict(os.environ,{'NEEDS_JSON':__import__('json').dumps(needs)}), self.assertRaises(AssertionError):exec(program,{})
        with patch.dict(os.environ,{'NEEDS_JSON':'{"detect":{"result":"failure"}}'}), self.assertRaises(AssertionError):exec(program,{})
