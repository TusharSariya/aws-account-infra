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
