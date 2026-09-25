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
            ".github/workflows/shell.yml",
        ]:
            self.assertTrue(changes.relevant("shell", [path]))

    def test_deleted_shell_paths_still_select_shell_checks(self):
        # The production detector uses git diff --name-only --no-renames, so a
        # deleted path reaches the same matcher as an existing path.
        self.assertTrue(changes.relevant("shell", ["scripts/retired-script.sh"]))
        self.assertTrue(changes.relevant("shell", ["tests/retired-test.bats"]))

    def test_runtime_and_filter_changes_invalidate_checks(self):
        for scope in changes.SCOPES:
            for path in [".github/actions/talos-runner-setup/action.yml", "scripts/ci-relevant-changes.py"]:
                self.assertTrue(changes.relevant(scope, [path]))

    def test_shell_shared_ci_dependencies(self):
        for path in [
            ".github/actions/talos-runner-setup/action.yml",
            ".github/actions/relevant-changes/action.yml",
            "scripts/ci-relevant-changes.py",
        ]:
            self.assertTrue(changes.relevant("shell", [path]))

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
