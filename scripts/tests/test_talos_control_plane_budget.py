"""The control plane is a 2 vCPU / 5 GiB guest on a laptop; its budget is reviewed here."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / 'config/environments/proxmox/homelab/talos/patches'


def mebibytes(value):
    match = re.fullmatch(r'(\d+)(MiB|Mi|GiB|Gi)', value)
    return int(match[1]) * (1024 if match[2].startswith('G') else 1)


class ControlPlaneBudgetTests(unittest.TestCase):
    def setUp(self):
        self.config = next(yaml.safe_load_all((PATCHES / 'talos-cp-01.yaml').read_text()))
        launch = (ROOT / 'platform/main-control-plane/launch.sh').read_text()
        self.vm_mib = int(re.search(r'-m (\d+)', launch)[1])

    def test_apiserver_heap_ceiling_and_request_fit_the_guest(self):
        api = self.config['cluster']['apiServer']
        limit = mebibytes(api['env']['GOMEMLIMIT'])
        request = mebibytes(api['resources']['requests']['memory'])
        # The heap ceiling leaves room for etcd, kubelet, Cilium and page cache.
        self.assertLessEqual(request, limit)
        self.assertLessEqual(limit, self.vm_mib * 0.35)
        self.assertNotIn('limits', api['resources'], 'A hard limit would restart the API server in a loop')

    def test_kubelet_evicts_before_the_host_oom_controller(self):
        extra = self.config['machine']['kubelet']['extraConfig']
        reserved = mebibytes(extra['systemReserved']['memory']) + mebibytes(extra['kubeReserved']['memory'])
        self.assertGreaterEqual(reserved, 512)
        self.assertLess(mebibytes(extra['evictionHard']['memory.available']),
                        mebibytes(extra['evictionSoft']['memory.available']))
        self.assertIn('memory.available', extra['evictionSoftGracePeriod'])

    def test_audit_policy_drops_churn_and_keeps_metadata_for_the_rest(self):
        policy = self.config['cluster']['apiServer']['auditPolicy']
        self.assertEqual(policy['kind'], 'Policy')
        self.assertEqual(policy['rules'][-1], {'level': 'Metadata'})
        silenced = {(r.get('group', ''), tuple(r['resources'])) for rule in policy['rules'][:-1]
                    for r in rule.get('resources', [])}
        self.assertIn(('coordination.k8s.io', ('leases',)), silenced)
        self.assertIn(('', ('events',)), silenced)
        # Every None rule is scoped to a resource, a non-resource URL, or the read
        # verbs of platform identities; user-facing writes stay audited.
        for rule in policy['rules'][:-1]:
            self.assertEqual(rule['level'], 'None')
            scoped = ('resources' in rule or 'nonResourceURLs' in rule
                      or set(rule.get('verbs', [])) <= {'get', 'list', 'watch'})
            self.assertTrue(scoped, rule)

    def test_workers_keep_the_default_budget(self):
        for name in ('talos-worker-01', 'talos-worker-02'):
            config = next(yaml.safe_load_all((PATCHES / (name + '.yaml')).read_text()))
            self.assertNotIn('apiServer', config.get('cluster', {}))
            self.assertNotIn('extraConfig', config['machine'].get('kubelet', {}))
