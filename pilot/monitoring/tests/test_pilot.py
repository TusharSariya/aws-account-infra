import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exporter import admitted_delay, worker_state  # noqa: E402
import common  # noqa: E402
import install  # noqa: E402


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


argo = module("bootstrap", ROOT.parent / "argocd/bootstrap.py")
app = module("application", ROOT.parent / "application/render.py")


class PilotTests(unittest.TestCase):
    def test_wrong_cluster_identity_stops_before_mutation(self):
        with (
            patch.object(
                common, "get", return_value={"metadata": {"uid": "production"}}
            ),
            patch.object(install, "kubectl") as mutation,
        ):
            with self.assertRaises(RuntimeError):
                install.apply({"apiVersion": "v1", "kind": "Namespace"})
            mutation.assert_not_called()

    def test_paused_worker_not_ready_is_distinct_from_missing_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "desired.json").write_text('{"target":1}')
            (state / "observed.json").write_text('{"name":"retired-worker"}')
            (state / "maintenance").touch()
            self.assertEqual(
                worker_state(state, []), (True, 1, False, "retired-worker")
            )
            (state / "maintenance").unlink()
            (state / "desired.json").write_text('{"target":0}')
            self.assertEqual(worker_state(state, [])[:3], (False, 0, False))

    def test_admission_uses_server_transition_and_ignores_false(self):
        workload = {
            "metadata": {"creationTimestamp": "2026-09-21T00:00:00Z"},
            "status": {
                "conditions": [
                    {
                        "type": "Admitted",
                        "status": "False",
                        "lastTransitionTime": "2026-09-21T00:00:03Z",
                    }
                ]
            },
        }
        self.assertIsNone(admitted_delay(workload))
        workload["status"]["conditions"][0]["status"] = "True"
        self.assertEqual(admitted_delay(workload), 3)

    def test_capacity_does_not_fall_back_to_workers(self):
        sample = {
            "management_available": 3 * 1024**3,
            "management_cpu_free": 1,
            "request_memory_free": 2 * 1024**3,
            "request_cpu_free": 1,
            "laptop_available": 1024**3,
        }
        self.assertTrue(argo.capacity([sample]))
        for key in sample:
            self.assertFalse(argo.capacity([sample, {**sample, key: 0}]), key)

    def test_private_repository_requires_credentials_before_cluster_writes(self):
        with patch.object(argo, "identity"), patch.object(argo, "kubectl") as mutation:
            with self.assertRaisesRegex(RuntimeError, "repository-token-file"):
                argo.configure_repository(None)
            mutation.assert_not_called()

    def test_missing_or_mutable_image_fails_closed(self):
        for image in [
            None,
            "",
            "ghcr.io/tusharsariyaorg/pilot-http:latest",
            "docker.io/foreign@sha256:" + "a" * 64,
        ]:
            with self.assertRaises(ValueError):
                app.render({"image": image})

    def test_app_is_namespace_scoped_unprivileged_and_never_pruned(self):
        rendered = app.render(
            {"image": "ghcr.io/tusharsariyaorg/pilot-http@sha256:" + "a" * 64}
        )
        for item in rendered["items"]:
            self.assertEqual(item["metadata"]["namespace"], "pilot-app")
            self.assertEqual(
                item["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                "Prune=false",
            )
        pod = rendered["items"][0]["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["nodeSelector"], {"prototype.homelab/pool": "workers"})

    def test_release_locks_are_checksums_not_latest(self):
        releases = json.loads((ROOT / "releases.json").read_text())
        for release in releases.values():
            self.assertRegex(release["sha256"], r"^[a-f0-9]{64}$")
            self.assertNotIn("/latest/", release["url"])


if __name__ == "__main__":
    unittest.main()
