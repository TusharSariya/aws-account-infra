"""Every routine workflow job routes through CI_EXECUTOR; hosted jobs are explicit exceptions."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github/workflows'

# Jobs that deliberately bypass the CI_EXECUTOR switch. '*' covers every job in
# the workflow. Anything not listed here must route through vars.CI_EXECUTOR so
# that routine CI runs on ARC and ubuntu-latest remains only the unset fallback.
CIRCULAR = {
    # Mutate the cluster, nodes or admission path that ARC runners depend on.
    ('homelab-ci-admission', 'admission'),
    ('homelab-worker-maintenance', '*'),
    ('homelab-lifecycle-maintenance', '*'),
    ('homelab-ai-migration', '*'),
    ('homelab-capacity-host', '*'),
    ('homelab-quota-acceptance', '*'),
    ('homelab-etcd-backup', '*'),
}
OFF_CLUSTER = {
    # Plan the Proxmox hosts and Talos control plane from outside the cluster.
    ('tofu-plan', 'proxmox-plan'),
    ('tofu-plan', 'talos-plan'),
}
HARD_WIRED_ARC = {
    # Pinned to a specific ARC scale set rather than the executor switch.
    ('homelab-arc-acceptance', '*'),
    ('inference-image', 'build'),
    ('postgres-backup-image', 'build'),
    # PRs use homelab-talos-checks; dispatched bootstrap falls back to hosted.
    ('homelab-ci-admission', 'contracts'),
}
ALLOWLIST = CIRCULAR | OFF_CLUSTER | HARD_WIRED_ARC


def jobs():
    for path in sorted(WORKFLOWS.glob('*.yml')):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for name, job in workflow.get('jobs', {}).items():
            if 'runs-on' in job:
                yield path.stem, name, str(job['runs-on'])


def covered(entries, workflow, job):
    return (workflow, job) in entries or (workflow, '*') in entries


class ExecutorRouting(unittest.TestCase):
    def test_routine_jobs_use_the_executor_switch(self):
        for workflow, job, runs_on in jobs():
            with self.subTest(job=f'{workflow}/{job}'):
                if 'CI_EXECUTOR' not in runs_on:
                    self.assertTrue(covered(ALLOWLIST, workflow, job),
                                    'route through vars.CI_EXECUTOR or add a reasoned allowlist entry')

    def test_hosted_by_design_jobs_do_not_use_arc_labels(self):
        for workflow, job, runs_on in jobs():
            if 'CI_EXECUTOR' in runs_on or covered(HARD_WIRED_ARC, workflow, job):
                continue
            if covered(CIRCULAR | OFF_CLUSTER, workflow, job):
                with self.subTest(job=f'{workflow}/{job}'):
                    self.assertIsNone(re.search(r'homelab-talos', runs_on))

    def test_allowlist_has_no_stale_entries(self):
        bypassing = {(workflow, job) for workflow, job, runs_on in jobs() if 'CI_EXECUTOR' not in runs_on}
        for workflow, job in ALLOWLIST:
            with self.subTest(entry=f'{workflow}/{job}'):
                if job == '*':
                    self.assertTrue(any(w == workflow for w, _ in bypassing))
                else:
                    self.assertIn((workflow, job), bypassing)


if __name__ == '__main__':
    unittest.main()
