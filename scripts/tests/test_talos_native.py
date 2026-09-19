"""Exercise blocking Cilium conditions against the real root with mock providers."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeContractTests(unittest.TestCase):
    def test_cilium_network_contract_blocks_invalid_public_values(self):
        for before, after in [(None, None), ('kubeProxyReplacement: false', 'kubeProxyReplacement: true'),
                              ('routingMode: tunnel', 'routingMode: native'),
                              ('tunnelProtocol: vxlan', 'tunnelProtocol: geneve'),
                              ('mode: kubernetes', 'mode: cluster-pool')]:
            with self.subTest(change=after), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tf = root / 'live/talos/homelab'
                shutil.copytree(ROOT / 'live/talos/homelab', tf,
                                ignore=shutil.ignore_patterns('.terraform', '*.tfstate*', '*.tfplan'))
                # Reuse initialized, pinned provider binaries; tests mock all provider operations.
                (tf / '.terraform').symlink_to(ROOT / 'live/talos/homelab/.terraform', target_is_directory=True)
                # OpenTofu 1.11 mock providers cannot import. Remove only the
                # bootstrap import in this disposable fixture, never the source root.
                main = tf / 'main.tf'
                fixture, count = re.subn(r'(?m)^import \{\n[^}]+^\}\n', '', main.read_text())
                self.assertEqual(count, 1)
                main.write_text(fixture)
                values_dir = root / 'config/environments/talos/homelab'
                shutil.copytree(ROOT / 'config/environments/talos/homelab', values_dir)
                values = values_dir / 'cilium-values.yaml'
                if before:
                    text = values.read_text()
                    self.assertIn(before, text)
                    values.write_text(text.replace(before, after))
                tests = tf / 'tests'
                tests.mkdir(exist_ok=True)
                expected = 'expect_failures = [helm_release.cilium]' if before else ''
                (tests / 'network.tftest.hcl').write_text('''
mock_provider "talos" {}
mock_provider "helm" {}
variables {
  client_configuration = { ca_certificate = "test", client_certificate = "test", client_key = "test" }
  machine_configurations = { talos-cp-01 = "test", talos-worker-01 = "test" }
  kubeconfig_path = "/unused-mocked-kubeconfig"
  worker_enabled = true
}
run "network_contract" {
  command = plan
  assert {
    condition = (
      talos_machine_configuration_apply.control_plane.node == "10.0.0.221" &&
      talos_machine_configuration_apply.control_plane.endpoint == "10.0.0.221" &&
      talos_machine_bootstrap.cluster.node == "10.0.0.221" &&
      talos_machine_bootstrap.cluster.endpoint == "10.0.0.221"
    )
    error_message = "Control-plane resources must use the current .221 address."
  }
  ''' + expected + '\n}\n')
                result = subprocess.run(['tofu', f'-chdir={tf}', 'test', '-no-color'],
                                        capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
