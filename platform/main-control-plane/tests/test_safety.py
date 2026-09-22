import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


placement = load("placement", REPO / "kubernetes/platform/main/placement/plan.py")
maintenance = load("maintenance", ROOT / "maintenance.py")
network = load("network", ROOT / "network.py")
capacity = load("capacity", ROOT / "capacity.py")


class SafetyTests(unittest.TestCase):
    def obj(self, kind="Deployment", namespace="homelab-cache", name="nexus"):
        return {
            "kind": kind,
            "metadata": {
                "namespace": namespace,
                "name": name,
                "uid": "unchanged",
                "resourceVersion": "42",
            },
            "spec": {
                "replicas": 1,
                "template": {"spec": {"nodeSelector": {"existing": "value"}}},
            },
        }

    def test_inventory_includes_qualified_resource_names(self):
        available = [
            "deployments.apps",
            "jobs.batch",
            "cronjobs.batch",
            "pods",
            "persistentvolumes",
            "persistentvolumeclaims",
        ]
        for kind in ["deployments", "jobs", "cronjobs", "pods", "pv", "pvc"]:
            self.assertTrue(maintenance.resource_available(kind, available))
        self.assertFalse(
            maintenance.resource_available("applications.argoproj.io", available)
        )

    def test_dormant_ai_is_untouched(self):
        obj = self.obj(namespace="homelab-models", name="ai-runtime")
        obj["spec"]["replicas"] = 0
        self.assertIsNone(placement.patch_for(obj))

    def test_storage_affinity_preserves_every_existing_term(self):
        obj = self.obj()
        pod = obj["spec"]["template"]["spec"]
        pod["affinity"] = {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {"matchExpressions": [{"key": "a", "operator": "Exists"}]},
                        {"matchExpressions": [{"key": "b", "operator": "Exists"}]},
                    ]
                }
            }
        }
        original = copy.deepcopy(obj)
        patches = placement.patch_for(obj)
        self.assertEqual(obj, original)
        self.assertEqual(patches[0]["value"], "unchanged")
        self.assertEqual(patches[1]["path"], "/spec")
        self.assertEqual(patches[1]["value"], original["spec"])
        terms = patches[2]["value"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"]
        for term in terms:
            self.assertEqual(len(term["matchExpressions"]), 2)
            self.assertEqual(term["matchExpressions"][-1]["values"], ["local-primary"])

    def test_local_claim_runners_cannot_move_to_secondary(self):
        obj = self.obj("AutoscalingRunnerSet", "arc-runners", "test")
        obj["spec"]["template"]["spec"]["volumes"] = [
            {"name": "data", "persistentVolumeClaim": {"claimName": "protected"}}
        ]
        result = placement.patch_for(obj)[2]["value"]
        self.assertEqual(
            result["template"]["spec"]["nodeSelector"]["homelab.tfdraw.dev/storage"],
            "local-primary",
        )
        self.assertEqual(
            result["listenerTemplate"]["spec"]["nodeSelector"][
                "homelab.tfdraw.dev/worker-role"
            ],
            "primary",
        )

    def test_active_work_blocks_shutdown(self):
        objects = {
            "jobs": [{"metadata": {"name": "job"}, "status": {"active": 1}}],
            "backups.postgresql.cnpg.io": [
                {"metadata": {"name": "backup"}, "status": {"phase": "running"}}
            ],
        }
        self.assertEqual(len(maintenance.blockers(objects)), 2)

    def test_schedules_and_submissions_must_be_paused(self):
        objects = {
            "cronjobs": [{"metadata": {"name": "schedule"}, "spec": {}}],
            "autoscalingrunnersets.actions.github.com": [
                {
                    "metadata": {"name": "runners"},
                    "spec": {"minRunners": 0, "maxRunners": 1},
                }
            ],
        }
        self.assertEqual(len(maintenance.blockers(objects)), 2)
        objects["cronjobs"][0]["spec"]["suspend"] = True
        objects["autoscalingrunnersets.actions.github.com"][0]["spec"]["maxRunners"] = 0
        self.assertEqual(maintenance.blockers(objects), [])

    def test_real_routes_require_fencing(self):
        with (
            patch.object(network.Path, "exists", return_value=False),
            patch.object(network.Path, "is_file", return_value=False),
            patch.object(network, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "fencing"):
                network.up(network.REAL, "tushar")
            run.assert_not_called()

    def test_capacity_rejects_low_memory_and_sustained_swapping(self):
        samples = [
            {
                "time": i * 15,
                "host_available": 1024**3,
                "guest_available": 1024**3,
                "swap_bytes": 0,
            }
            for i in range(5)
        ]
        self.assertTrue(capacity.passes(samples))
        samples[-1]["host_available"] = 511 * 1024**2
        self.assertFalse(capacity.passes(samples))
        samples[-1]["host_available"] = 1024**3
        for i, sample in enumerate(samples):
            sample["swap_bytes"] = i * 15 * 65536
        self.assertFalse(capacity.passes(samples))

    def test_capacity_rejects_counter_reset_and_observation_gap(self):
        samples = [
            {
                "time": i * 15,
                "host_available": 1024**3,
                "guest_available": 1024**3,
                "swap_bytes": 100,
            }
            for i in range(5)
        ]
        samples[-1]["swap_bytes"] = 0
        self.assertFalse(capacity.passes(samples))
        samples[-1]["swap_bytes"] = 100
        samples[-1]["time"] = 200
        self.assertFalse(capacity.passes(samples))

    def test_linux_interface_names_fit(self):
        import re

        text = (ROOT / "ops.sh").read_text()
        for name in re.findall(r"\bmcptest-[a-z]+\b", text):
            self.assertLessEqual(len(name), 15)


if __name__ == "__main__":
    unittest.main()
