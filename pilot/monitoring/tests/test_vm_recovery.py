import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "monitoring"))
sys.path.insert(0, str(ROOT / "vm"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


prepare = load("prepare_disks", ROOT / "vm/prepare_disks.py")
recovery = load("recovery", ROOT / "vm/recovery.py")
autoscaler = load("autoscaler", ROOT / "controllers/autoscaler.py")
sys.path.append(str(ROOT / "monitoring/kubernetes"))
host_restore = load("host_restore", ROOT / "monitoring/kubernetes/restore_host.py")
acceptance = load("portable_acceptance", ROOT / "monitoring/kubernetes/accept.py")


class RecoveryTests(unittest.TestCase):
    def test_preparation_refuses_existing_vm_without_touching_files(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp) / "vm"
            vm.mkdir()
            disk = vm / "PROTOTYPE-control-plane.qcow2"
            disk.write_bytes(b"existing cluster")
            with self.assertRaises(FileExistsError):
                prepare.prepare(vm)
            self.assertEqual(disk.read_bytes(), b"existing cluster")

    def test_corrupt_download_cannot_create_disks(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "cache"
            cache.mkdir()
            (cache / "metal-amd64.iso").write_bytes(b"incorrect")
            with patch.object(prepare.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    prepare.prepare(Path(temp) / "new", cache)
                run.assert_not_called()

    def test_recovery_check_detects_state_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            hashes = {}
            for name in [
                "controlplane.machineconfig.yaml",
                "etcd.snapshot",
                "talosconfig",
                "kubeconfig",
                "nodes.json",
                "volumes.json",
            ]:
                (directory / name).write_bytes(b"original")
                hashes[name] = hashlib.sha256(b"original").hexdigest()
            (directory / "etcd.snapshot").write_bytes(b"changed")
            (directory / "manifest.json").write_text(
                json.dumps(
                    {
                        "sha256": hashes,
                        "kube_system_uid": recovery.PROFILE["kube_system_uid"],
                    }
                )
            )
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                recovery.check(directory)

    def test_incomplete_recovery_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "manifest.json").write_text('{"sha256": {}}')
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                recovery.check(directory)

    def test_autoscaler_tuning_preserves_other_controls(self):
        before = [
            "--scale-down-enabled=false",
            "--max-node-provision-time=15m",
            "--provisioning-request-initial-backoff-time=10s",
            "--provisioning-request-max-backoff-time=30s",
        ]
        after = autoscaler.tuned(before)
        self.assertEqual(after[:2], before[:2])
        self.assertEqual(
            after[2:],
            [
                "--provisioning-request-initial-backoff-time=2s",
                "--provisioning-request-max-backoff-time=5s",
                "--scan-interval=2s",
            ],
        )
        with self.assertRaises(RuntimeError):
            autoscaler.tuned(before + [before[-1]])


class HostRecoveryTests(unittest.TestCase):
    def test_mismatched_credentials_stop_before_creating_host_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "backup"
            private.mkdir()
            (private / "host-token").write_text("wrong-token")
            destination = root / "host-state"
            with (
                patch.object(host_restore, "identity"),
                patch.object(host_restore, "BASE", destination),
                patch.object(
                    host_restore,
                    "get",
                    return_value={
                        "data": {"token": base64.b64encode(b"expected-token").decode()}
                    },
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "do not match"):
                    host_restore.restore(private)
            self.assertFalse(destination.exists())


class ReaderNamespaceTests(unittest.TestCase):
    def test_renewal_preserves_existing_namespace_security_policy(self):
        import install

        existing = {
            "items": [
                {
                    "metadata": {
                        "name": name,
                        "labels": {"pod-security.kubernetes.io/enforce": "restricted"},
                    }
                }
                for name in ["pilot-monitoring", "pilot-app"]
            ]
        }
        with (
            patch.object(install, "get", return_value=existing),
            patch.object(install, "apply") as apply,
        ):
            install.ensure_reader_namespaces()
            apply.assert_not_called()

    def test_missing_namespace_starts_restricted(self):
        import install

        with (
            patch.object(install, "get", return_value={"items": []}),
            patch.object(install, "apply") as apply,
        ):
            install.ensure_reader_namespaces()
            self.assertEqual(apply.call_count, 2)
            for call in apply.call_args_list:
                self.assertEqual(
                    call.args[0]["metadata"]["labels"][
                        "pod-security.kubernetes.io/enforce"
                    ],
                    "restricted",
                )


class AcceptanceModeTests(unittest.TestCase):
    def test_monitoring_only_cannot_bypass_load_or_ignore_installed_argo(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for passed, namespaces, message in [
                (False, [], "Fresh passing"),
                (True, [{"metadata": {"name": "pilot-argocd"}}], "Argo is present"),
            ]:
                (base / "measurement.json").write_text(
                    json.dumps({"passed": passed, "mode": "kubernetes", "ended": 100})
                )
                with (
                    patch.object(acceptance, "BASE", base),
                    patch.object(acceptance, "identity"),
                    patch.object(acceptance.time, "time", return_value=101),
                    patch.object(acceptance, "get", return_value={"items": namespaces}),
                    patch.object(acceptance, "logs") as logs,
                ):
                    with self.assertRaisesRegex(RuntimeError, message):
                        acceptance.main(monitoring_only=True)
                    logs.assert_not_called()
