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

    def test_ansible_and_shell_are_independent(self):
        self.assertTrue(changes.relevant("ansible", ["ansible/playbooks/site.yml"]))
        self.assertFalse(changes.relevant("shell", ["ansible/playbooks/site.yml"]))
        self.assertTrue(changes.relevant("shell", ["scripts/example.sh"]))
        self.assertFalse(changes.relevant("ansible", ["scripts/example.sh"]))

    def test_runtime_and_filter_changes_invalidate_checks(self):
        for scope in changes.SCOPES:
            for path in [".github/actions/talos-runner-setup/action.yml", "scripts/ci-relevant-changes.py"]:
                self.assertTrue(changes.relevant(scope, [path]))

    def test_localstack_dependencies(self):
        self.assertTrue(changes.relevant("localstack", ["apps/ecr/court-booker/tests/test_api.py"]))
        self.assertFalse(changes.relevant("localstack", ["apps/containers/ollama/Dockerfile"]))


if __name__ == "__main__":
    unittest.main()
