"""Routine jobs route through CI_EXECUTOR, cluster maintenance through CI_OPERATOR."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github/workflows'

# The operator runners on the owner's Mac (docs/runbooks/mac-operator-runner.md):
# Linux containers by default or the native macOS runner, both labelled
# homelab-operator, with hosted ubuntu-latest as the fallback while
# vars.CI_OPERATOR is unset. No OS label, so either form can take the job.
OPERATOR = ("vars.CI_OPERATOR == 'mac' && "
            """fromJSON('["self-hosted","homelab-operator"]') || 'ubuntu-latest'""")

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
    # External coordinator and helpers control the hosts running ARC.
    ('retained-power-deploy', 'deploy'),
    # Initial freeze RBAC must not depend on admission by that coordinator.
    ('retained-power-deploy', 'freeze-rbac'),
    ('homelab-quota-acceptance', '*'),
    ('homelab-etcd-backup', '*'),
}
# Circular or bootstrap jobs that stay hosted and never use CI_OPERATOR.
HOSTED_ONLY = {
    # Daily cron must not depend on the operator Mac being awake; age is Linux amd64.
    ('homelab-etcd-backup', '*'),
    # Builds a linux/amd64 image with Docker, which the operator runner lacks.
    ('ci-runner-image', 'build'),
}
# Operator jobs whose runs-on also carries a CI_EXECUTOR branch for other units.
MIXED_OPERATOR = {
    # Proxmox/Talos units use the operator expression; other units follow CI_EXECUTOR.
    ('tofu-apply', 'apply'),
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
    # PRs use homelab-talos-checks; dispatched bootstrap uses the off-cluster
    # operator runners (CI_OPERATOR) and falls back to hosted.
    ('homelab-ci-admission', 'contracts'),
}
ALLOWLIST = CIRCULAR | OFF_CLUSTER | HARD_WIRED_ARC


def job_specs():
    for path in sorted(WORKFLOWS.glob('*.yml')):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for name, job in workflow.get('jobs', {}).items():
            if 'runs-on' in job:
                yield path.stem, name, str(job['runs-on']), job


def jobs():
    for workflow, name, runs_on, _ in job_specs():
        yield workflow, name, runs_on


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

    def test_cluster_maintenance_uses_the_operator_switch(self):
        operator_jobs = (CIRCULAR | OFF_CLUSTER) - HOSTED_ONLY
        for workflow, job, runs_on in jobs():
            if covered(operator_jobs, workflow, job):
                with self.subTest(job=f'{workflow}/{job}'):
                    self.assertEqual(runs_on, '${{ ' + OPERATOR + ' }}')
                    self.assertNotIn('CI_EXECUTOR', runs_on)
                    self.assertNotIn('homelab-talos', runs_on)
            elif covered(MIXED_OPERATOR, workflow, job):
                with self.subTest(job=f'{workflow}/{job}'):
                    self.assertIn('(' + OPERATOR + ')', runs_on)

    def test_hosted_only_jobs_never_use_the_operator(self):
        seen = set()
        for workflow, job, runs_on in jobs():
            for entry in HOSTED_ONLY:
                if covered({entry}, workflow, job):
                    seen.add(entry)
                    with self.subTest(job=f'{workflow}/{job}'):
                        self.assertNotIn('CI_OPERATOR', runs_on)
                        self.assertNotIn('homelab-operator', runs_on)
        self.assertEqual(seen, HOSTED_ONLY, 'stale HOSTED_ONLY entry')

    def test_operator_jobs_require_the_prod_environment(self):
        # prod holds the operator secrets and OIDC trust; it is unrestricted because PR
        # plans and apply-before-merge deploy from refs/pull/N/merge. See
        # docs/runbooks/mac-operator-runner.md for the main-only hardening path.
        operator_jobs = [(workflow, name, job) for workflow, name, runs_on, job in job_specs()
                         if 'CI_OPERATOR' in runs_on or 'homelab-operator' in runs_on]
        self.assertTrue(operator_jobs)
        for workflow, name, job in operator_jobs:
            with self.subTest(job=f'{workflow}/{name}'):
                environment = job.get('environment')
                if isinstance(environment, dict):
                    environment = environment.get('name')
                self.assertEqual(environment, 'prod')


if __name__ == '__main__':
    unittest.main()
