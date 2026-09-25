"""Operator runners on the Mac run the ARC image in containers with a bounded footprint."""
from pathlib import Path
import re
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / 'platform/operator-runner/compose.yaml'
ENTRYPOINT = ROOT / 'platform/operator-runner/container-entrypoint.sh'
VALUES = ROOT / 'config/environments/kubernetes/homelab-ci/arc-runner-values.yaml'
SCRIPT = ROOT / 'scripts/mac-operator-containers.sh'


class OperatorContainerTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load(COMPOSE.read_text())
        self.services = self.compose['services']

    def test_runners_share_the_arc_image_pin_and_the_linux_code_path(self):
        pinned = set(re.findall(r'ghcr\.io/tusharsariyaorg/homelab-ci-runner@sha256:[0-9a-f]{64}', VALUES.read_text()))
        self.assertEqual(len(pinned), 1, 'arc-runner-values.yaml must pin exactly one runner digest')
        # The script resolves the digest from the ARC values at run time, so the
        # compose file must not carry a second copy that could drift.
        self.assertNotIn('@sha256:', COMPOSE.read_text())
        self.assertIn('pinned_image', SCRIPT.read_text())
        for name, service in self.services.items():
            with self.subTest(service=name):
                self.assertEqual(service['platform'], 'linux/amd64')
                self.assertEqual(service['image'], '${OPERATOR_RUNNER_IMAGE:?set by scripts/mac-operator-containers.sh}')

    def test_every_runner_is_isolated_and_bounded(self):
        self.assertEqual(sorted(self.services), ['runner-1', 'runner-2', 'runner-3'])
        for name, service in self.services.items():
            with self.subTest(service=name):
                self.assertEqual(service['cap_add'], ['NET_ADMIN'])
                self.assertEqual(service['devices'], ['/dev/net/tun:/dev/net/tun'])
                self.assertNotIn('privileged', service)
                self.assertNotIn('network_mode', service)
                self.assertNotIn('pid', service)
                self.assertEqual(service['cpus'], 4)
                self.assertEqual(service['mem_limit'], '4g')
                env = service['environment']
                self.assertEqual(env['RUNNER_LABELS'], 'homelab-operator')
                self.assertEqual(env['RUNNER_URL'], 'https://github.com/TusharSariyaOrg')
                self.assertTrue(env['RUNNER_NAME_PREFIX'].startswith('mac-operator-'))
                self.assertEqual(env['RUNNER_INDEX'], name.split('-')[1])
                mounts = [volume.split(':') for volume in service['volumes']]
                host_mounts = [m for m in mounts if m[0].startswith('.') or m[0].startswith('/')]
                self.assertEqual(host_mounts, [['./container-entrypoint.sh', '/opt/operator-runner/entrypoint.sh', 'ro']])
                self.assertFalse(any('docker.sock' in volume for volume in service['volumes']))
                named = {m[0] for m in mounts if m[0][0].isalpha()}
                self.assertEqual(named, {'state-' + env['RUNNER_INDEX'], 'work-' + env['RUNNER_INDEX']})
        self.assertEqual(set(self.compose['volumes']),
                         {'state-1', 'state-2', 'state-3', 'work-1', 'work-2', 'work-3'})

    def test_entrypoint_keeps_the_token_out_of_the_running_container(self):
        text = ENTRYPOINT.read_text()
        self.assertIn('unset RUNNER_TOKEN', text)
        self.assertIn('--runnergroup', text)
        self.assertIn('--replace', text)
        self.assertIn('--disableupdate', text)
        self.assertNotIn('echo "$RUNNER_TOKEN', text)
        self.assertNotIn('set -x', text)
        subprocess.run(['bash', '-n', str(ENTRYPOINT)], check=True)
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)

    def test_compose_renders_with_the_script_environment(self):
        try:
            result = subprocess.run(
                ['docker', 'compose', '-f', str(COMPOSE), 'config', '--no-interpolate', '--quiet'],
                capture_output=True, text=True)
        except FileNotFoundError:
            self.skipTest('docker unavailable on this runner')
        if result.returncode != 0 and 'compose' in result.stderr and 'not a docker command' in result.stderr:
            self.skipTest('docker compose plugin unavailable')
        self.assertEqual(result.returncode, 0, result.stderr)
