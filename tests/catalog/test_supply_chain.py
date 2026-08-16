import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class SupplyChainIaCTests(unittest.TestCase):
    def test_addons_are_pinned_gated_and_argocd_has_no_cluster_role(self):
        defaults = yaml.safe_load(
            (ROOT / "ansible/roles/cluster_addons/defaults/main.yml").read_text()
        )
        helmfile = (ROOT / "ansible/roles/cluster_addons/templates/helmfile.yaml.j2").read_text()
        self.assertEqual(defaults["cluster_addons_argocd_version"], "10.3.3")
        self.assertEqual(defaults["cluster_addons_kyverno_version"], "3.8.2")
        self.assertFalse(defaults["cluster_addons_argocd_enabled"])
        self.assertFalse(defaults["cluster_addons_kyverno_enabled"])
        self.assertFalse(defaults["cluster_addons_kyverno_image_verification_enabled"])
        self.assertIn("createClusterRoles: false", helmfile)
        self.assertIn("priorityClassName: platform-critical", helmfile)

    def test_image_policy_is_fail_closed_and_exact_identity(self):
        policy = (ROOT / "ansible/roles/cluster_addons/templates/kyverno-image-policy.yml.j2").read_text()
        self.assertIn("failurePolicy: Fail", policy)
        self.assertIn("certificate_identity", policy)
        self.assertIn("certificate_issuer", policy)
        self.assertIn("registry_secret_name", policy)
        self.assertNotIn("password:", policy)
        defaults = yaml.safe_load(
            (ROOT / "ansible/roles/cluster_addons/defaults/main.yml").read_text()
        )
        self.assertEqual(
            defaults["cluster_addons_kyverno_certificate_identity"],
            "https://github.com/TusharSariyaOrg/aws-account-infra/.github/workflows/ecr-push.yml@refs/heads/main",
        )

    def test_publish_role_cannot_manage_repositories(self):
        policy = (ROOT / "modules/aws/account_identity/ecr_push_oidc.tf").read_text()
        self.assertNotIn("ecr:CreateRepository", policy)
        self.assertNotIn("ecr:PutLifecyclePolicy", policy)
        self.assertIn("image-publish", policy)

    def test_ecr_lifecycle_preserves_supply_chain_artifacts(self):
        repository = (ROOT / "live/aws/staging/workloads/court-booker/ecr.tf").read_text()
        module = (ROOT / "modules/aws/ecr_repository/main.tf").read_text()
        self.assertIn("preserve_oci_reference_artifacts = true", repository)
        self.assertIn('tagPrefixList = ["image-"]', module)

    def test_gateway_owns_https_redirect_and_active_namespace_filter(self):
        gateway = (ROOT / "ansible/roles/cluster_addons/templates/gateway-resources.yml.j2").read_text()
        self.assertIn("protocol: HTTPS", gateway)
        self.assertIn("name: homelab-tls", gateway)
        self.assertIn("type: RequestRedirect", gateway)
        self.assertIn("platform.homelab.tfdraw.dev/active-tenant", gateway)


if __name__ == "__main__":
    unittest.main()
