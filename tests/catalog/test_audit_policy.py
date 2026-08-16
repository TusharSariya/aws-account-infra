import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class AuditPolicyTests(unittest.TestCase):
    def test_secret_bodies_are_never_logged(self):
        policy = yaml.safe_load(
            (ROOT / "ansible/roles/kubernetes_control_plane/templates/audit-policy.yml.j2").read_text()
        )
        secret_rule = policy["rules"][0]
        self.assertEqual(secret_rule["level"], "Metadata")
        self.assertIn("secrets", secret_rule["resources"][0]["resources"])

    def test_sensitive_control_changes_keep_request_content(self):
        policy = (ROOT / "ansible/roles/kubernetes_control_plane/templates/audit-policy.yml.j2").read_text()
        self.assertIn("level: RequestResponse", policy)
        self.assertIn('resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]', policy)
        self.assertIn('resources: ["pods/exec", "pods/attach", "pods/portforward"]', policy)


if __name__ == "__main__":
    unittest.main()
