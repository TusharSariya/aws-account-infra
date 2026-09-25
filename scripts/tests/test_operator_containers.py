"""Operator runners on the Mac: one fresh ARC-image container per job, bounded footprint."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / 'platform/operator-runner/supervise.sh'
VALUES = ROOT / 'config/environments/kubernetes/homelab-ci/arc-runner-values.yaml'
SCRIPT = ROOT / 'scripts/mac-operator-containers.sh'


def docker_run_flags():
    text = SUPERVISOR.read_text()
    match = re.search(r'docker run (.*?)"\$OPERATOR_RUNNER_IMAGE" /home/runner/run\.sh', text, re.S)
    assert match, 'supervisor must start the pinned image with run.sh'
    return match[1].replace('\\\n', ' ').split()


class OperatorContainerTests(unittest.TestCase):
    def test_runners_share_the_arc_image_pin_and_the_linux_code_path(self):
        pinned = set(re.findall(r'ghcr\.io/tusharsariyaorg/homelab-ci-runner@sha256:[0-9a-f]{64}', VALUES.read_text()))
        self.assertEqual(len(pinned), 1, 'arc-runner-values.yaml must pin exactly one runner digest')
        # The script resolves the digest from the ARC values at run time; no second copy.
        digest = re.compile(r'@sha256:[0-9a-f]{64}')
        self.assertIsNone(digest.search(SUPERVISOR.read_text()))
        self.assertIsNone(digest.search(SCRIPT.read_text()))
        self.assertIn('pinned_image', SCRIPT.read_text())
        self.assertIn('--platform linux/amd64', ' '.join(docker_run_flags()))

    def test_every_job_gets_a_fresh_isolated_bounded_container(self):
        flags = docker_run_flags()
        joined = ' '.join(flags)
        self.assertIn('--rm', flags)
        self.assertIn('--init', flags)
        self.assertEqual(flags.count('--cap-add'), 1)
        self.assertIn('--cap-add NET_ADMIN', joined)
        self.assertIn('--device /dev/net/tun:/dev/net/tun', joined)
        self.assertIn('--cpus 4', joined)
        self.assertIn('--memory 4g', joined)
        for forbidden in ('--privileged', '-v ', '--volume', '--mount', 'docker.sock', '--network host', '--pid'):
            self.assertNotIn(forbidden, joined + ' ')
        # The single-use JIT configuration reaches the container only as an
        # environment variable of that one container.
        self.assertIn('-e ACTIONS_RUNNER_INPUT_JITCONFIG', joined)
        self.assertNotIn('ACTIONS_RUNNER_INPUT_JITCONFIG=', joined)

    def test_jit_registration_targets_the_restricted_group_and_leaves_no_credentials(self):
        text = SUPERVISOR.read_text()
        self.assertIn('generate-jitconfig', text)
        self.assertIn('runner_group_id=${OPERATOR_GROUP_ID}', text)
        # JIT registration adds no default labels; runs-on requires self-hosted.
        for label in ('self-hosted', 'Linux', 'X64', '${LABEL}'):
            self.assertIn('labels[]=' + label, text)
        self.assertIn('readonly LABEL=homelab-operator', text)
        self.assertIn('name="mac-operator-${OPERATOR_HOST}-${OPERATOR_SLOT}-', text)
        self.assertNotIn('homelab-talos', text)
        self.assertNotIn('config.sh', text)
        self.assertNotIn('set -x', text)
        self.assertNotIn('echo "$ACTIONS_RUNNER_INPUT_JITCONFIG', text)
        self.assertIn('unset ACTIONS_RUNNER_INPUT_JITCONFIG', text)
        self.assertIn('readonly GROUP=homelab-operator', SCRIPT.read_text())
        subprocess.run(['bash', '-n', str(SUPERVISOR)], check=True)
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)
